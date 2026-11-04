import base64
import copy
import hashlib
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import zipfile

from studio import Studio, defaults, validate, detect_decal, fingerprint
from server import make_server
from obs import OBS


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.s = Studio(clock=lambda: self.now)
        self.s.config['bestof'] = 3
        self.s.armed = True

    def advance(self, seconds):
        self.now += seconds
        self.s.tick()

    def packet(self, event, **data):
        return self.s.ingest(dict(Event=event, Data=data))

    def test_entire_series(self):
        self.s.start()
        self.assertEqual(self.s.phase, 'pre')
        self.advance(13)
        self.assertEqual(self.s.phase, 'game')
        self.packet('MatchEnded', WinnerTeamNum=1, MatchGuid='one')
        self.assertEqual(self.s.phase, 'stats')
        self.advance(9.9)
        self.assertEqual(self.s.phase, 'stats')
        self.advance(.1)
        self.assertEqual(self.s.phase, 'game')
        self.packet('MatchStarted')
        self.packet('MatchEnded', WinnerTeamNum=1, MatchGuid='two')
        self.assertEqual(self.s.phase, 'victory1')
        self.advance(4)
        self.assertEqual(self.s.phase, 'stats')
        self.advance(10)
        self.assertEqual(self.s.phase, 'complete')
        self.assertEqual(self.s.history, ['pre', 'game', 'stats', 'game', 'victory1', 'stats', 'complete'])

    def test_duplicate_end_does_not_restart_timer(self):
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='one')
        deadline = self.s.deadline
        self.advance(5)
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='one')
        self.assertEqual(self.s.config['teams'][0]['wins'], 1)
        self.assertEqual(self.s.deadline, deadline)
        self.packet('MatchStarted')
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='one')
        self.assertEqual(self.s.config['teams'][0]['wins'], 1)

    def test_end_without_guid(self):
        self.packet('MatchEnded', WinnerTeamNum=0)
        self.packet('MatchEnded', WinnerTeamNum=0)
        self.assertEqual(self.s.config['teams'][0]['wins'], 1)
        self.packet('MatchStarted')
        self.packet('MatchEnded', WinnerTeamNum=0)
        self.assertEqual(self.s.phase, 'victory0')

    def test_early_kickoff_preserves_result_and_timer(self):
        self.s.match['players'] = [dict(Name='Player', TeamNum=0, Goals=4)]
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='one')
        result = copy.deepcopy(self.s.postmatch)
        self.packet('MatchStarted')
        self.packet('UpdateState', Game=dict(TimeSeconds=300, Teams=[dict(TeamNum=0, Score=0), dict(TeamNum=1, Score=0)]), Players=[dict(Name='Other', TeamNum=0)])
        self.assertEqual(self.s.postmatch, result)
        self.assertEqual(self.s.phase, 'stats')
        self.packet('MatchDestroyed')
        self.assertEqual(self.s.postmatch, result)

    def test_hold_extend_resume_cut(self):
        self.s.transition('stats', 10)
        self.advance(3)
        self.s.duration('hold')
        self.advance(100)
        self.assertEqual(self.s.phase, 'stats')
        self.s.duration('extend')
        self.s.duration('hold')
        self.advance(16)
        self.assertEqual(self.s.phase, 'stats')
        self.s.duration('cut')
        self.assertEqual(self.s.phase, 'game')

    def test_even_series_tie_skips_victory(self):
        self.s.config['bestof'] = 2
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='one')
        self.packet('MatchStarted')
        self.packet('MatchEnded', WinnerTeamNum=1, MatchGuid='two')
        self.assertEqual(self.s.phase, 'stats')
        self.advance(10)
        self.assertEqual(self.s.phase, 'complete')

    def test_manual_live_is_not_overwritten(self):
        self.s.correct([4, 3], 92, True, [1, 0], [dict(Name='Edited', TeamNum=0, Goals=4)])
        self.packet('UpdateState', Game=dict(TimeSeconds=40, Teams=[dict(TeamNum=0, Score=9)]), Players=[])
        self.assertEqual(self.s.match['scores'], [4, 3])
        self.assertEqual(self.s.match['time'], 92)
        self.s.manual_live = False
        self.packet('ClockUpdatedSeconds', TimeSeconds=20)
        self.assertEqual(self.s.match['time'], 20)

    def test_result_correction_preserves_live(self):
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='one')
        self.s.correct([5, 2], 0, False, [1, 0], [dict(Name='Edited', TeamNum=0, Goals=5)], result=True)
        self.assertEqual(self.s.postmatch['match']['scores'], [5, 2])
        self.assertEqual(self.s.match['scores'], [0, 0])
        with self.assertRaises(ValueError):
            self.s.correct([0, 0], 0, False, [2, 2], [])

    def test_before_start_end_is_ignored(self):
        self.s.armed = False
        self.packet('MatchEnded', WinnerTeamNum=0, MatchGuid='old')
        self.assertEqual(self.s.config['teams'][0]['wins'], 0)

    def test_json_text_data_and_bad_packet(self):
        self.s.ingest(dict(Event='MatchEnded', Data=json.dumps(dict(WinnerTeamNum=0, MatchGuid='one'))))
        self.assertEqual(self.s.phase, 'stats')
        self.assertFalse(self.s.ingest(dict(Event='UpdateState', Data='bad')))

    def test_manual_series_without_api(self):
        self.s.finish(0)
        self.s.manual_next()
        self.assertEqual(self.s.phase, 'game')
        self.assertEqual(self.s.match['scores'], [0, 0])
        self.s.finish(0)
        self.assertEqual(self.s.phase, 'victory0')
        with self.assertRaises(ValueError):
            self.s.manual_next()


class AssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logo = self.root/'logo.png'
        self.logo.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=='))

    def profile(self):
        p = defaults()
        for i, team in enumerate(p['teams']):
            team.update(name='Team '+str(i), short='T'+str(i), logo=str(self.logo))
        return p

    def package(self, name, body):
        path = self.root/name
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('skin.json', json.dumps({'decal': {'BodyID': body}}))
            z.writestr('skin.png', b'image')
        return path

    def test_required_fields(self):
        p = self.profile()
        validate(p)
        for key in ('name', 'short', 'logo', 'color', 'car'):
            broken = copy.deepcopy(p)
            broken['teams'][0][key] = ''
            with self.assertRaises(ValueError, msg=key):
                validate(broken)

    def test_decal_three_cars_and_mismatch(self):
        for body, car in ((23, 'Octane'), (4284, 'Fennec'), (403, 'Dominus')):
            path = self.package(str(body)+'.zip', body)
            self.assertEqual(detect_decal(path), car)
        p = self.profile()
        p['teams'][0]['skin'] = str(self.package('bad.zip', 4284))
        with self.assertRaises(ValueError):
            validate(p)
        with self.assertRaises(ValueError):
            detect_decal(self.package('unsupported.zip', 999999))

    def test_unknown_image_requires_confirmation(self):
        p = self.profile()
        p['teams'][0]['skin'] = str(self.logo)
        with self.assertRaises(ValueError):
            validate(p)
        p['teams'][0]['skin_confirmed'] = 'Octane'
        validate(p)

    def test_media_fingerprint_changes(self):
        p = self.profile()
        previous = fingerprint(p)
        p['teams'][0]['car'] = 'Dominus'
        self.assertNotEqual(fingerprint(p), previous)

    def test_http_range_and_local_routes(self):
        movie = self.root/'test.mp4'
        movie.write_bytes(b'0123456789')
        server = make_server(Studio(), {'fingerprint': 'test', 'files': {'pre': str(movie)}}, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        for route in ('/program', '/overlay', '/postmatch', '/state', '/boost-animation.js', '/assets/torneo.png'):
            with urlopen(url+route) as response:
                self.assertEqual(response.status, 200)
        with urlopen(Request(url+'/media/pre', headers={'Range': 'bytes=2-5'})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b'2345')
        with self.assertRaises(HTTPError) as ctx:
            urlopen(url+'/../app.py')
        self.assertEqual(ctx.exception.code, 404)


class OBSProtocolTests(unittest.TestCase):
    def test_real_socket_auth_masked_frames_and_request(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        self.addCleanup(listener.close)
        errors = []
        def server():
            try:
                sock, _ = listener.accept()
                with sock:
                    sock.settimeout(3)
                    stream = sock.makefile('rb')
                    request = b''
                    while not request.endswith(b'\r\n\r\n'):
                        request += stream.read(1)
                    key = next(l.split(b': ', 1)[1] for l in request.split(b'\r\n') if l.startswith(b'Sec-WebSocket-Key:'))
                    accept = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                    sock.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n')
                    def send(value):
                        raw = json.dumps(value).encode()
                        sock.sendall(b'\x81'+(bytes([len(raw)]) if len(raw)<126 else b'\x7e'+struct.pack('!H', len(raw)))+raw)
                    def receive():
                        _, length = stream.read(2)
                        self.assertTrue(length & 128)
                        size = length & 127
                        if size == 126:
                            size = struct.unpack('!H', stream.read(2))[0]
                        mask = stream.read(4)
                        return json.loads(bytes(x ^ mask[i%4] for i, x in enumerate(stream.read(size))))
                    send(dict(op=0, d=dict(rpcVersion=1, authentication=dict(salt='salt', challenge='challenge'))))
                    identify = receive()
                    secret = base64.b64encode(hashlib.sha256(b'passwordsalt').digest())
                    expected = base64.b64encode(hashlib.sha256(secret+b'challenge').digest()).decode()
                    self.assertEqual(identify['d']['authentication'], expected)
                    send(dict(op=2, d=dict(negotiatedRpcVersion=1)))
                    req = receive()
                    self.assertEqual(req['d']['requestType'], 'GetVersion')
                    send(dict(op=7, d=dict(requestId=req['d']['requestId'], requestStatus=dict(result=True), responseData=dict(obsVersion='test'))))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        obs = OBS()
        self.addCleanup(obs.close)
        obs.connect(listener.getsockname()[1], 'password')
        self.assertEqual(obs.request('GetVersion'), {'obsVersion': 'test'})
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
