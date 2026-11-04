import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from vendor.overlay.app import preview_snapshot

ROOT = Path(__file__).resolve().parent


def make_server(store, media, port=18767):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            route = urlsplit(self.path).path
            if route in ('/state', '/preview-state'):
                state = preview_snapshot(store) if route == '/preview-state' else store.snapshot()
                state['media'] = {key: '/media/'+key+'?v='+media.get('version', media['fingerprint']) for key in media.get('files', {})}
                data = json.dumps(state, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                if not head:
                    self.wfile.write(data)
                return
            routes = {'/': ROOT/'program.html', '/program': ROOT/'program.html',
                      '/overlay': ROOT/'vendor/overlay/overlay.html',
                      '/postmatch': ROOT/'vendor/postmatch/postmatch.html',
                      '/boost-animation.js': ROOT/'vendor/overlay/boost-animation.js',
                      '/assets/torneo.png': ROOT/'vendor/overlay/assets/torneo.png'}
            path = routes.get(route)
            if route.startswith('/media/'):
                value = media.get('files', {}).get(route[len('/media/'):])
                path = Path(value) if value else None
            if path is None or not path.is_file():
                self.send_error(404)
                return
            size = path.stat().st_size
            start, end = 0, size-1
            partial = False
            if self.headers.get('Range'):
                import re
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers['Range'])
                if match and any(match.groups()):
                    a, b = match.groups()
                    if a:
                        start, end = int(a), min(int(b), size-1) if b else size-1
                    else:
                        start = max(0, size-int(b))
                    partial = True
                else:
                    start = size
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.end_headers()
                    return
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(end-start+1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-cache')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not head:
                try:
                    with path.open('rb') as file:
                        file.seek(start)
                        remaining = end-start+1
                        while remaining:
                            chunk = file.read(min(262144, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (ConnectionError, BrokenPipeError):
                    pass
    try:
        return ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except OSError:
        return ThreadingHTTPServer(('127.0.0.1', 0), Handler)
