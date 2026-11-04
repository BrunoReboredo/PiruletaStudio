"""Small local obs-websocket 5 client; no third party runtime dependencies."""
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import uuid

SCENES = dict(pre='Piruleta · Prepartido', game='Piruleta · Partido',
              stats='Piruleta · Estadísticas', victory0='Piruleta · Victoria A',
              victory1='Piruleta · Victoria B', complete='Piruleta · Fin')
SOURCE = 'Piruleta · Programa'


class OBS:
    def __init__(self):
        self.sock = None
        self.buffer = b''
        self.lock = threading.RLock()

    def close(self):
        if self.sock:
            self.sock.close()
        self.sock = None
        self.buffer = b''

    def read(self, size):
        while len(self.buffer) < size:
            chunk = self.sock.recv(max(4096, size-len(self.buffer)))
            if not chunk:
                raise ConnectionError('OBS ha cerrado la conexión.')
            self.buffer += chunk
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def send(self, payload, opcode=1):
        if isinstance(payload, dict):
            payload = json.dumps(payload).encode()
        mask = os.urandom(4)
        size = len(payload)
        header = bytes([0x80 | opcode])
        header += bytes([0x80 | size]) if size < 126 else (b'\xfe' + struct.pack('!H', size) if size < 65536 else b'\xff' + struct.pack('!Q', size))
        self.sock.sendall(header + mask + bytes(x ^ mask[i % 4] for i, x in enumerate(payload)))

    def receive(self):
        chunks = []
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self.read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self.read(8))[0]
            if size > 8_000_000:
                raise ValueError('Respuesta OBS demasiado grande.')
            mask = self.read(4) if second & 128 else None
            payload = self.read(size)
            if mask:
                payload = bytes(x ^ mask[i % 4] for i, x in enumerate(payload))
            opcode = first & 15
            if opcode == 8:
                raise ConnectionError('OBS ha cerrado la conexión. Revisa la contraseña.')
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise ValueError('Respuesta WebSocket no compatible.')
            chunks.append(payload)
            if first & 128:
                return json.loads(b''.join(chunks).decode())

    def connect(self, port=4455, password=''):
        with self.lock:
            self.close()
            try:
                self.sock = socket.create_connection(('127.0.0.1', int(port)), timeout=3)
                self.sock.settimeout(3)
                key = base64.b64encode(os.urandom(16)).decode()
                self.sock.sendall((f'GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
                while b'\r\n\r\n' not in self.buffer:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        raise ConnectionError('OBS no respondió al saludo.')
                    self.buffer += chunk
                    if len(self.buffer) > 65536:
                        raise ValueError('Saludo OBS inválido.')
                headers, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
                accept = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
                fields = dict(line.split(b':', 1) for line in headers.split(b'\r\n')[1:] if b':' in line)
                fields = {k.lower(): v.strip() for k, v in fields.items()}
                if b' 101 ' not in headers.split(b'\r\n')[0] or fields.get(b'sec-websocket-accept') != accept:
                    raise ConnectionError('El puerto no corresponde a obs-websocket 5.')
                hello = self.receive()
                if hello.get('op') != 0:
                    raise ValueError('OBS no ha enviado Hello.')
                identify = dict(rpcVersion=1, eventSubscriptions=0)
                auth = hello['d'].get('authentication')
                if auth:
                    secret = base64.b64encode(hashlib.sha256((password+auth['salt']).encode()).digest()).decode()
                    identify['authentication'] = base64.b64encode(hashlib.sha256((secret+auth['challenge']).encode()).digest()).decode()
                self.send(dict(op=1, d=identify))
                if self.receive().get('op') != 2:
                    raise ConnectionError('OBS no ha aceptado la conexión.')
            except Exception:
                self.close()
                raise

    def request(self, kind, **data):
        with self.lock:
            if not self.sock:
                raise ConnectionError('Conecta OBS primero.')
            request_id = uuid.uuid4().hex
            try:
                self.send(dict(op=6, d=dict(requestType=kind, requestId=request_id, requestData=data)))
                while True:
                    response = self.receive()
                    if response.get('op') == 7 and response['d'].get('requestId') == request_id:
                        d = response['d']
                        if not d['requestStatus']['result']:
                            raise RuntimeError(d['requestStatus'].get('comment', str(d['requestStatus'])))
                        return d.get('responseData', {})
            except (OSError, ValueError, ConnectionError):
                self.close()
                raise

    def prepare(self, url):
        scenes = {s['sceneName'] for s in self.request('GetSceneList')['scenes']}
        inputs = {s['inputName'] for s in self.request('GetInputList')['inputs']}
        for scene in SCENES.values():
            if scene not in scenes:
                self.request('CreateScene', sceneName=scene)
        settings = dict(url=url+'/program', width=1920, height=1080,
                        shutdown=False, restart_when_active=False, reroute_audio=True)
        if SOURCE not in inputs:
            self.request('CreateInput', sceneName=SCENES['pre'], inputName=SOURCE,
                         inputKind='browser_source', inputSettings=settings, sceneItemEnabled=True)
        else:
            self.request('SetInputSettings', inputName=SOURCE, inputSettings=settings, overlay=True)
        for scene in SCENES.values():
            items = self.request('GetSceneItemList', sceneName=scene)['sceneItems']
            if not any(item['sourceName'] == SOURCE for item in items):
                self.request('CreateSceneItem', sceneName=scene, sourceName=SOURCE, sceneItemEnabled=True)
        # This changes only the two Piruleta victory scenes, so series wins cut immediately.
        transitions = self.request('GetSceneTransitionList')['transitions']
        cut = next((t['transitionName'] for t in transitions if t.get('transitionKind') == 'cut_transition'), None)
        if cut:
            for phase in ('victory0', 'victory1'):
                self.request('SetSceneSceneTransitionOverride', sceneName=SCENES[phase], transitionName=cut)

    def switch(self, phase):
        self.request('SetCurrentProgramScene', sceneName=SCENES[phase])
