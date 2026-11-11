"""Standalone Rocket League postmatch overlay. Python 3.11+, standard library only."""
import copy
import json
from pathlib import Path
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser
from .boost_usage import BoostUsage
from .roster import normalize_player, merge_players

ROOT = Path(__file__).resolve().parent
APP_VERSION = '0.1.0'
SERIES_FORMATS = (1, 2, 3, 4, 5, 7)
MAX_LOGO_BYTES = 4_000_000
MAX_LOGO_DATA_URL_CHARS = ((MAX_LOGO_BYTES + 2) // 3) * 4 + 64


def series_state(config):
    bestof = config['bestof']
    wins = [team['wins'] for team in config['teams']]
    target = bestof//2 + 1
    complete = max(wins) >= target or sum(wins) >= bestof
    tied = complete and wins[0] == wins[1]
    return {'target': target, 'complete': complete, 'tied': tied,
            'game': min(bestof, sum(wins) + (0 if complete else 1)),
            'slots': target}


def swap_team_sides(config):
    """Move identities and series wins; live game telemetry keeps its game-side indexes."""
    swapped = copy.deepcopy(config)
    swapped['teams'].reverse()
    colors = swapped['colors']
    colors['pink'], colors['yellow'] = colors['yellow'], colors['pink']
    backgrounds = swapped['panel_colors']
    remap = {'pink': 'yellow', 'yellow': 'pink'}
    left, right = backgrounds['players0'], backgrounds['players1']
    backgrounds['players0'], backgrounds['players1'] = remap.get(right, right), remap.get(left, left)
    return swapped


from vendor.overlay.app import DEFAULT, normalize_config, swap_team_sides
from .basic_metrics import DEFAULT_METRICS, normalize_metrics


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.config = copy.deepcopy(DEFAULT)
        self.config['metrics'] = list(DEFAULT_METRICS)
        self.match = {'scores': [0, 0], 'time': 300, 'overtime': False,
                      'players': [], 'target': '', 'banner': ''}
        self.status = 'Conexión automática · esperando Rocket League'
        self.finished = set()
        self.banner_until = 0
        self.automatic = False
        self.last_update = 0
        self.postmatch = None
        self.boost_usage = BoostUsage()
        self.match_guid = None
        self.roster = []

    def snapshot(self):
        with self.lock:
            if time.monotonic() > self.banner_until:
                self.match['banner'] = ''
            return copy.deepcopy({'config': self.config, 'match': self.match,
                                  'series': series_state(self.config),
                                  'postmatch': self.postmatch,
                                  'connection': {'automatic': self.automatic,
                                                 'receiving': self.last_update > 0 and time.monotonic()-self.last_update < 5,
                                                 'status': self.status}})

    def ingest(self, packet):
        if not isinstance(packet, dict):
            return False
        event, d = packet.get('Event'), packet.get('Data', {})
        # The live game serializes Data as JSON text; documentation examples
        # also use an embedded object. Accept both transport representations.
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except json.JSONDecodeError:
                return False
        if not isinstance(d, dict):
            return False
        with self.lock:
            m = self.match
            if event == 'UpdateState':
                g = d.get('Game', {})
                if not isinstance(g, dict) or not isinstance(d.get('Players', []), list):
                    return False
                for t in g.get('Teams', []):
                    i = t.get('TeamNum')
                    if i in (0, 1):
                        m['scores'][i] = max(0, int(t.get('Score', 0)))
                m['time'] = int(g.get('TimeSeconds', m['time']))
                m['overtime'] = bool(g.get('bOvertime', False))
                guid = d.get('MatchGuid')
                if (guid and guid != self.match_guid) or (self.postmatch and m['scores'] == [0, 0] and m['time'] > 0 and d.get('Players')):
                    self.boost_usage.reset()
                    self.roster = []
                    self.postmatch = None
                if guid:
                    self.match_guid = guid
                players = []
                for player in d.get('Players', []):
                    player = normalize_player(player)
                    if player is None:
                        continue
                    player = dict(player)
                    # Live spectator packets omit Boost when it is zero. Only
                    # infer zero if spectator car telemetry is actually present.
                    if player.get('Boost') is None and any(key in player for key in
                            ('bHasCar', 'Speed', 'bBoosting', 'bOnGround', 'bOnWall', 'bDemolished')):
                        player['Boost'] = 0
                    players.append(player)
                self.boost_usage.update(players, replay=bool(g.get('bReplay', False)))
                if not g.get('bReplay', False):
                    self.roster = merge_players(self.roster, players)
                else:
                    identities = [{k:p[k] for k in ('Name','TeamNum','PrimaryId','Shortcut') if k in p} for p in players]
                    self.roster = merge_players(self.roster, identities)
                m['players'] = merge_players(self.roster)
                m['target'] = (g.get('Target') or {}).get('Name', '')
                # A new kickoff clears the previous result; menu/destruction packets do not.
                if self.postmatch and players and m['scores'] == [0, 0] and m['time'] > 0:
                    self.postmatch = None
                self.last_update = time.monotonic()
            elif event == 'ClockUpdatedSeconds':
                m['time'] = int(d.get('TimeSeconds', 0))
                m['overtime'] = bool(d.get('bOvertime', False))
            elif event == 'GoalScored':
                self.boost_usage.boundary(active=False)
                # Goals update from UpdateState; no on-screen goal/scorer messages.
                m['banner'] = ''
                self.banner_until = 0
            elif event == 'MatchEnded':
                self.boost_usage.boundary(active=False)
                winner, guid = d.get('WinnerTeamNum'), d.get('MatchGuid')
                if winner in (0, 1):
                    new_result = not self.postmatch or (guid and self.postmatch['guid'] != guid)
                    if new_result:
                        self.postmatch = {
                            'guid': guid, 'winner': winner,
                            'match': copy.deepcopy(m),
                            'config': copy.deepcopy(self.config),
                        }
                    m['banner'] = 'VICTORIA · ' + self.config['teams'][winner]['name']
                    self.banner_until = time.monotonic() + 12
                    if self.config['auto_series'] and guid and guid not in self.finished:
                        self.finished.add(guid)
                        if not series_state(self.config)['complete']:
                            self.config['teams'][winner]['wins'] += 1
                            self.config['game'] = series_state(self.config)['game']
                    if new_result:
                        self.postmatch['wins'] = [team['wins'] for team in self.config['teams']]
            elif event in ('MatchStarted', 'MatchCreated', 'MatchInitialized'):
                guid = d.get('MatchGuid')
                if event != 'MatchInitialized' or guid != self.match_guid or self.postmatch is not None:
                    self.postmatch = None
                    self.roster = []
                    self.boost_usage.reset()
                    self.match_guid = guid
                if event != 'MatchStarted':
                    self.boost_usage.boundary(False)
            elif event in ('CountdownBegin', 'RoundStarted', 'MatchUnpaused', 'GoalReplayEnd'):
                self.boost_usage.boundary(active=event in ('RoundStarted', 'MatchUnpaused'))
            elif event in ('MatchPaused', 'GoalReplayStart'):
                self.boost_usage.boundary(active=False)
            elif event == 'MatchDestroyed':
                self.roster = []
                self.boost_usage.reset()
                self.match_guid = None
                m['players'], m['target'] = [], ''
            else:
                return False
            return True


class GameConnection:
    """Official TCP Stats API; handles concatenated/fragmented JSON objects."""
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.thread = None

    def connect(self, port):
        self.disconnect()
        self.store.automatic = True
        self.store.last_update = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, args=(port, self.stop), daemon=True)
        self.thread.start()

    def disconnect(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.store.status = 'Desconectado'
        self.store.automatic = False
        self.store.last_update = 0

    def run(self, port, stop):
        decoder = json.JSONDecoder()
        while not stop.is_set():
            self.store.status = 'Conectando a Rocket League…'
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1) as sock:
                    sock.settimeout(.5)
                    self.store.status = 'Conectado · esperando datos del partido'
                    buf = b''
                    while not stop.is_set():
                        try:
                            chunk = sock.recv(65536)
                        except socket.timeout:
                            if self.store.last_update and time.monotonic()-self.store.last_update > 5:
                                self.store.status = 'Conectado · sin datos recientes (menú o partido finalizado)'
                            continue
                        if not chunk:
                            break
                        buf += chunk
                        # Decode only complete UTF-8 sequences; JSON can span packets.
                        try:
                            text = buf.decode('utf-8')
                        except UnicodeDecodeError:
                            continue
                        text = text.lstrip('\x00\ufeff\r\n ')
                        while text:
                            try:
                                packet, end = decoder.raw_decode(text)
                            except json.JSONDecodeError:
                                break
                            if isinstance(packet, dict):
                                accepted = self.store.ingest(packet)
                                if accepted and packet.get('Event') == 'UpdateState':
                                    self.store.status = 'En directo · tiempo y goles sincronizados con Rocket League'
                                elif not accepted and packet.get('Event') == 'UpdateState':
                                    self.store.status = 'Conectado · actualización del juego no reconocida'
                            text = text[end:].lstrip('\x00\r\n ')
                        buf = text.encode('utf-8')
                        if len(buf) > 4_000_000:
                            raise ValueError('Formato TCP no reconocido')
            except (OSError, ValueError, TypeError) as exc:
                self.store.status = f'Sin conexión · {exc}'
            if not stop.is_set():
                self.store.last_update = 0
                self.store.status = 'Esperando Rocket League · reconexión automática'
                stop.wait(2)


def preview_snapshot(store):
    """Example data for preview only; never writes to the live match or connection."""
    snapshot = store.snapshot()
    snapshot['match'] = {
        'scores': [2, 1], 'time': 193, 'overtime': False, 'target': 'PIRU', 'banner': '',
        'players': [{'Name': name, 'TeamNum': i//3, 'Boost': boost,
                     'Score': 541 if i == 0 else 125+i*32, 'Goals': 2 if i == 0 else i%2,
                     'Shots': 5, 'Assists': 1, 'Saves': 3}
                    for i, (name, boost) in enumerate([('PIRU', 72), ('CANDY', 38), ('FRESA', 100),
                                                      ('MANGO', 54), ('POP', 0), ('LIMÓN', 91)])]}
    snapshot['postmatch'] = {
        'guid': 'preview', 'winner': 0, 'match': copy.deepcopy(snapshot['match']),
        'config': copy.deepcopy(snapshot['config']), 'wins': [2, 1],
    }
    final = snapshot['postmatch']
    final['visible'] = True
    final['match']['scores'] = [3, 1]
    final['config']['game'] = 3
    for i, player in enumerate(final['match']['players']):
        player.update(BoostUsed=[1420, 1185, 1630, 1545, 1270, 1380][i], Goals=[2, 1, 0, 1, 0, 0][i],
                      Assists=[0, 1, 2, 0, 1, 0][i],
                      Shots=[5, 3, 2, 4, 2, 1][i], Saves=[1, 2, 0, 3, 1, 2][i])
    return snapshot


def make_server(store, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            route = self.path.split('?')[0]
            if route in ('/state', '/preview-state'):
                state = preview_snapshot(store) if route == '/preview-state' else store.snapshot()
                data = json.dumps(state, ensure_ascii=False).encode('utf-8')
                mime = 'application/json; charset=utf-8'
            elif route in ('/', '/postmatch'):
                data = (ROOT / 'postmatch.html').read_bytes()
                mime = 'text/html; charset=utf-8'
            elif route in ('/assets/torneo.png', '/assets/pluma.png'):
                data = (ROOT / route.lstrip('/')).read_bytes()
                mime = 'image/png'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (ConnectionResetError, BrokenPipeError):
                pass
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


class App:
    def __init__(self, root):
        self.root, self.store = root, Store()
        self.file = ROOT / 'ultimo_perfil.json'
        if self.file.exists():
            try:
                self.store.config = normalize_config(json.loads(self.file.read_text('utf-8')))
            except (OSError, ValueError, TypeError, KeyError):
                pass
        self.connection = GameConnection(self.store)
        try:
            self.server = make_server(self.store, 18766)
        except OSError:
            self.server = make_server(self.store)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/postmatch'
        root.title('Piruleta - Estadísticas')
        self.app_icon = tk.PhotoImage(master=root, file=str(ROOT / 'assets' / 'pluma.png'))
        root.iconphoto(True, self.app_icon)
        root.geometry('920x740')
        root.minsize(860, 720)
        root.configure(bg='#181426')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background='#181426', foreground='white', font=('Segoe UI', 10))
        style.configure('TEntry', fieldbackground='#30283d', foreground='white', insertcolor='white')
        style.configure('TSpinbox', fieldbackground='#30283d', foreground='white')
        style.configure('TCombobox', fieldbackground='#30283d', foreground='white')
        style.map('TCombobox', fieldbackground=[('readonly', '#30283d')], foreground=[('readonly', 'white')])
        style.configure('TButton', padding=(10, 7), background='#44304c')
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='PIRULETA - ESTADÍSTICAS', foreground='#fa54b7',
                  font=('Segoe UI', 23, 'bold')).pack(anchor='w', pady=(0, 14))
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(0, 14))
        ttk.Button(bar, text='Vista previa', command=self.preview).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Copiar URL para OBS', command=self.copy_url).pack(side='left')
        ttk.Label(bar, text='Fuente Navegador · 1920 × 1080').pack(side='right')
        notebook = ttk.Notebook(outer)
        notebook.pack(fill='both', expand=True)
        teams, design = (ttk.Frame(notebook, padding=18) for _ in range(2))
        notebook.add(teams, text='Equipos y serie')
        notebook.add(design, text='Diseño')
        self.vars = {}
        self.team_vars = [{}, {}]
        self.field(teams, 'Torneo', 'event')
        self.field(teams, 'Ronda', 'round')
        self.field(teams, 'Formato BO', 'bestof', [str(n) for n in SERIES_FORMATS])
        self.field(teams, 'Partido', 'game')
        for i in range(2):
            row = ttk.Frame(teams)
            row.pack(fill='x', pady=8)
            ttk.Label(row, text=f'Equipo {i+1}', width=18).pack(side='left')
            name = tk.StringVar()
            wins = tk.StringVar()
            self.team_vars[i] = {'name': name, 'wins': wins}
            ttk.Entry(row, textvariable=name).pack(side='left', fill='x', expand=True)
            ttk.Button(row, text='Escudo…', command=lambda i=i: self.logo(i)).pack(side='left', padx=5)
            ttk.Button(row, text='Quitar', command=lambda i=i: self.logo(i, clear=True)).pack(side='left')
            ttk.Label(row, text='  Victorias ').pack(side='left')
            ttk.Spinbox(row, from_=0, to=4, textvariable=wins, width=3).pack(side='left')
        self.auto = tk.BooleanVar()
        ttk.Checkbutton(teams, text='Sumar victorias automáticamente al finalizar', variable=self.auto).pack(anchor='w', pady=10)
        row = ttk.Frame(teams)
        row.pack(fill='x', pady=8)
        ttk.Button(row, text='Cambiar equipos de lado', command=self.swap).pack(side='left')
        ttk.Button(row, text='Reiniciar serie', command=self.reset).pack(side='left', padx=8)
        ttk.Label(teams, text='Los resultados conservan los equipos y el diseño del momento en que termina el partido.\n'
                  'El overlay permanece transparente hasta el final y desaparece al comenzar el siguiente.',
                  wraplength=760).pack(anchor='w', pady=14)
        palette = ttk.Frame(design)
        palette.pack(fill='x', pady=10)
        for key, title in [('pink', 'Equipo A'), ('coral', 'Coral'), ('yellow', 'Equipo B'), ('dark', 'Fondo'), ('text', 'Texto')]:
            ttk.Button(palette, text=title, command=lambda k=key: self.color(k)).pack(side='left', padx=3)
        self.field(design, 'Tipografía', 'font', ['Arial', 'Segoe UI', 'Verdana', 'Trebuchet MS', 'Impact'])
        self.field(design, 'Estilo', 'design', ['angular', 'rounded', 'classic'])
        self.field(design, 'Opacidad (%)', 'opacity')
        self.logos = tk.BooleanVar()
        ttk.Checkbutton(design, text='Mostrar escudos', variable=self.logos).pack(anchor='w', pady=8)
        ttk.Label(design, text='CSS libre (opcional)').pack(anchor='w')
        self.css = tk.Text(design, height=5, bg='#30283d', fg='white', insertbackground='white')
        self.css.pack(fill='both', expand=True, pady=6)
        footer = ttk.Frame(outer)
        footer.pack(fill='x', pady=12)
        ttk.Button(footer, text='Aplicar', command=self.apply).pack(side='right')
        ttk.Button(footer, text='Guardar perfil…', command=self.save).pack(side='left')
        ttk.Button(footer, text='Cargar perfil…', command=self.load).pack(side='left', padx=8)
        self.status = ttk.Label(outer, wraplength=840, foreground='#ffd14c')
        self.status.pack(anchor='w')
        self.sync()
        self.connection.connect(self.store.config['api_port'])
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()

    def field(self, parent, title, key, choices=None):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=5)
        ttk.Label(row, text=title, width=18).pack(side='left')
        var = tk.StringVar()
        self.vars[key] = var
        widget = ttk.Combobox(row, textvariable=var, values=choices, state='readonly') if choices else ttk.Entry(row, textvariable=var)
        widget.pack(side='left', fill='x', expand=True)

    def sync(self):
        c = self.store.snapshot()['config']
        for k, var in self.vars.items():
            var.set(str(c[k]))
        for i, fields in enumerate(self.team_vars):
            for k, var in fields.items():
                var.set(str(c['teams'][i][k]))
        self.auto.set(c['auto_series'])
        self.logos.set(c['show_logos'])
        self.css.delete('1.0', 'end')
        self.css.insert('1.0', c['custom_css'])
        self.last_series = (c['game'], tuple(t['wins'] for t in c['teams']))

    def apply(self):
        try:
            with self.store.lock:
                raw = copy.deepcopy(self.store.config)
                raw.update({k: v.get() for k, v in self.vars.items()})
                for i, fields in enumerate(self.team_vars):
                    raw['teams'][i].update({k: v.get() for k, v in fields.items()})
                raw.update(auto_series=self.auto.get(), show_logos=self.logos.get(), custom_css=self.css.get('1.0', 'end-1c'))
                self.store.config = normalize_config(raw)
            return True
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Revisa el perfil', str(exc))
            return False

    def preview(self):
        if self.apply():
            webbrowser.open(self.url+'?preview=1')

    def copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url)
        messagebox.showinfo('URL copiada', self.url+'\n\nOBS → Navegador → 1920 × 1080')

    def color(self, key):
        value = colorchooser.askcolor(self.store.config['colors'][key])[1]
        if value:
            with self.store.lock:
                self.store.config['colors'][key] = value

    def logo(self, i, clear=False):
        if clear:
            value = ''
        else:
            path = filedialog.askopenfilename(filetypes=[('Imagen PNG', '*.png')])
            if not path:
                return
            import base64
            data = Path(path).read_bytes()
            if len(data) > MAX_LOGO_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                messagebox.showerror('Escudo', 'Elige un PNG de hasta 4 MB.')
                return
            value = 'data:image/png;base64,'+base64.b64encode(data).decode('ascii')
        with self.store.lock:
            self.store.config['teams'][i]['logo'] = value

    def swap(self):
        if self.apply():
            with self.store.lock:
                self.store.config = swap_team_sides(self.store.config)
            self.sync()

    def reset(self):
        with self.store.lock:
            for team in self.store.config['teams']:
                team['wins'] = 0
            self.store.config['game'] = 1
        self.sync()

    def save(self):
        if not self.apply():
            return
        path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Perfil', '*.json')])
        if path:
            Path(path).write_text(json.dumps(self.store.snapshot()['config'], ensure_ascii=False, indent=2), 'utf-8')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Perfil PostMatch o marcador', '*.json')])
        if not path:
            return
        try:
            config = normalize_config(json.loads(Path(path).read_text('utf-8')))
            with self.store.lock:
                self.store.config = config
            self.sync()
            self.connection.connect(config['api_port'])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror('Perfil', str(exc))

    def refresh(self):
        c = self.store.snapshot()['config']
        current = (c['game'], tuple(t['wins'] for t in c['teams']))
        if current != self.last_series:
            self.vars['game'].set(str(c['game']))
            for i in range(2):
                self.team_vars[i]['wins'].set(str(c['teams'][i]['wins']))
            self.last_series = current
        self.status.configure(text=self.store.status+'\nOBS: '+self.url)
        self.root.after(250, self.refresh)

    def close(self):
        if not self.apply():
            return
        self.file.write_text(json.dumps(self.store.snapshot()['config'], ensure_ascii=False, indent=2), 'utf-8')
        self.connection.disconnect()
        self.server.shutdown()
        self.server.server_close()
        self.root.destroy()


if __name__ == '__main__':
    App(tk.Tk()).root.mainloop()
