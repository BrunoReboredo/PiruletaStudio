"""Piruleta - Overlay. Python 3.11+, standard library only."""
import copy
import json
import os
import re
from pathlib import Path
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser

from vendor.postmatch.basic_metrics import DEFAULT_METRICS, normalize_metrics

ROOT = Path(__file__).resolve().parent
APP_VERSION = '1.0.0'
# Private online, offline exhibition and local LAN lobby.
PRIVATE_PLAYLISTS = frozenset((6, 8, 24))
SERIES_FORMATS = (1, 2, 3, 4, 5, 7)
MAX_LOGO_BYTES = 4_000_000
MAX_LOGO_DATA_URL_CHARS = ((MAX_LOGO_BYTES + 2) // 3) * 4 + 64


FONT_DIRECTORY = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PiruletaOverlay' / 'fonts'
STANDARD_FONTS = ('Montserrat', 'Arial', 'Segoe UI', 'Verdana', 'Trebuchet MS', 'Impact')
FONT_TYPES = {
    '.ttf': ('font/ttf', (b'\x00\x01\x00\x00', b'true')),
    '.otf': ('font/otf', (b'OTTO',)),
    '.woff': ('font/woff', (b'wOFF',)),
    '.woff2': ('font/woff2', (b'wOF2',)),
}
CUSTOM_FONT_PREFIX = 'Personalizada · '
MAX_FONT_BYTES = 16 * 1024 * 1024


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
    for panel in ('boost', 'stats'):
        a, b = backgrounds[panel+'0'], backgrounds[panel+'1']
        backgrounds[panel+'0'], backgrounds[panel+'1'] = remap.get(b, b), remap.get(a, a)
    return swapped


DEFAULT = {
    'metrics': DEFAULT_METRICS, 'mvp_delay': 3.0,
    'event': 'TORNEO PIRULETA', 'round': 'GRAN FINAL', 'game': 1, 'bestof': 5,
    'teams': [{'name': 'PINK CANDY', 'logo': '', 'wins': 0},
              {'name': 'GOLDEN POP', 'logo': '', 'wins': 0}],
    'colors': {'pink': '#fa54b7', 'coral': '#ff8875', 'yellow': '#ffd14c',
               'dark': '#181426', 'text': '#ffffff'},
    'show_logos': True, 'show_players': True, 'show_stats': True,
    'show_boost': True, 'show_events': True,
    'design': 'rounded', 'font': 'Verdana', 'scale': 100, 'opacity': 100,
    'x': 360, 'y': 0, 'auto_series': True, 'custom_css': '', 'api_port': 49123,
    'scoreboard_gradient': True,
    'goal_style': 'Torneo Piruleta', 'design_presets': {}, 'rck_layout_revision': 2,
    'panel_colors': {'boost0': 'pink', 'boost1': 'yellow', 'stats0': 'pink', 'stats1': 'yellow',
                     'players0': 'dark', 'players1': 'dark', 'boost': 'dark', 'stats': 'dark'},
    'panels': {'players0': [24, 180, 100], 'players1': [1601, 180, 100],
               'focus': [36, 880, 100], 'boost': [1695, 860, 120],
               'banner': [460, 370, 100]},
}


DESIGN_FIELDS = ('colors', 'panels', 'panel_colors', 'x', 'y', 'scale')


def switch_design(raw, previous):
    """Keep the regular layout and RCK layout independent across style changes."""
    old_group = 'RCK' if previous == 'RCK' else 'standard'
    new_group = 'RCK' if raw['design'] == 'RCK' else 'standard'
    if old_group == new_group:
        return raw
    raw = copy.deepcopy(raw)
    presets = raw.setdefault('design_presets', {})
    presets[old_group] = {key: copy.deepcopy(raw[key]) for key in DESIGN_FIELDS}
    incoming = copy.deepcopy(presets.get(new_group))
    if incoming is None:
        incoming = {key: copy.deepcopy(DEFAULT[key]) for key in DESIGN_FIELDS}
        if new_group == 'RCK':
            incoming['colors'].update(pink='#BEB4E6', yellow='#99C6DA', coral='#d9e0eb', dark='#04174A', text='#ffffff')
            incoming.update(x=500, y=0, scale=100)
            incoming['panels'].update(players0=[24, 190, 100], players1=[1601, 190, 100],
                                      focus=[36, 925, 100], boost=[1695, 860, 120])
            incoming['panel_colors'].update(players0='dark', players1='dark', stats0='pink', stats1='yellow', boost0='dark', boost1='dark')
    raw.update(incoming)
    return raw


def normalize_config(raw):
    """Validate profiles before they reach widgets or the overlay."""
    if not isinstance(raw, dict):
        raise ValueError('El perfil debe ser un objeto JSON.')
    c = copy.deepcopy(DEFAULT)
    c['metrics'] = normalize_metrics(raw.get('metrics', DEFAULT_METRICS))
    delay = float(raw.get('mvp_delay',3))
    if not .5 <= delay <= 30:
        raise ValueError('La espera tras MVP debe estar entre 0,5 y 30 segundos.')
    c['mvp_delay'] = delay
    for key in ('event', 'round', 'font'):
        if key in raw:
            c[key] = str(raw[key])[:120]
    for key, lo, hi in [('game', 1, 99), ('bestof', 1, 15), ('scale', 50, 150),
                        ('opacity', 10, 100), ('x', 0, 1900), ('y', 0, 1000), ('api_port', 1, 65535)]:
        c[key] = max(lo, min(hi, int(raw.get(key, c[key]))))
    if c['bestof'] not in SERIES_FORMATS:
        raise ValueError('Elige BO1, BO2, BO3, BO4, BO5 o BO7.')
    c['game'] = min(c['game'], c['bestof'])
    for key in c:
        if key.startswith('show_') or key == 'auto_series':
            c[key] = bool(raw.get(key, c[key]))
    if raw.get('design') in ('angular', 'rounded', 'classic', 'RCK'):
        c['design'] = raw['design']
    if raw.get('goal_style') == 'Original':
        c['goal_style'] = 'Torneo Piruleta'
    if raw.get('goal_style') in ('Torneo Piruleta', 'Bigness League', 'RCS', 'RCK'):
        c['goal_style'] = raw['goal_style']
    c['scoreboard_gradient'] = bool(raw.get('scoreboard_gradient', True))
    for panel in ('boost', 'stats'):
        legacy = raw.get('panel_colors', {}).get(panel)
        if legacy in c['colors']:
            c['panel_colors'][panel+'0'] = legacy
            c['panel_colors'][panel+'1'] = legacy
    c['custom_css'] = str(raw.get('custom_css', ''))[:50000]
    for key, value in raw.get('panel_colors', {}).items():
        if key in c['panel_colors'] and value in c['colors']:
            c['panel_colors'][key] = value
    for key, values in raw.get('panels', {}).items():
        if key in c['panels'] and isinstance(values, list) and len(values) == 3:
            c['panels'][key] = [max(0, min(1920, int(values[0]))),
                                max(0, min(1080, int(values[1]))),
                                max(25, min(200, int(values[2])))]
    for key, value in raw.get('colors', {}).items():
        if key in c['colors'] and isinstance(value, str) and len(value) == 7:
            int(value[1:], 16)
            if value.startswith('#'):
                c['colors'][key] = value
    for i, team in enumerate(raw.get('teams', [])[:2]):
        c['teams'][i] = {'name': str(team.get('name', 'EQUIPO'))[:80],
                         'logo': str(team.get('logo', ''))[:MAX_LOGO_DATA_URL_CHARS],
                         'short': str(team.get('short', ''))[:80],
                         'wins': max(0, min(c['bestof']//2+1, int(team.get('wins', 0))))}
    if sum(t['wins'] for t in c['teams']) > c['bestof']:
        raise ValueError('Las victorias superan los partidos del formato. Reinicia la serie antes de cambiarlo.')
    presets = raw.get('design_presets', {})
    if isinstance(presets, dict):
        for group in ('standard', 'RCK'):
            if isinstance(presets.get(group), dict):
                # Normalize cached layouts without recursively copying caches.
                saved = normalize_config({'design': 'RCK' if group == 'RCK' else 'rounded',
                                          'rck_layout_revision': raw.get('rck_layout_revision', 1),
                                          **{key: presets[group][key] for key in DESIGN_FIELDS if key in presets[group]}})
                c['design_presets'][group] = {key: copy.deepcopy(saved[key]) for key in DESIGN_FIELDS}
    # Early RCK releases overwrote the regular layout in existing profiles.
    # Recognize the exact shipped preset rather than treating user colors as RCK.
    rck_palette = {'pink': '#bdb0e4', 'yellow': '#96c9da', 'coral': '#d9e0eb',
                   'dark': '#071640', 'text': '#ffffff'}
    if (c['design'] != 'RCK' and not c['design_presets']
            and c['colors'] == rck_palette and c['y'] == 36
            and c['panels']['focus'] == [76, 944, 100]
            and c['panels']['boost'] == [1590, 775, 140]):
        c['design_presets']['RCK'] = {key: copy.deepcopy(c[key]) for key in DESIGN_FIELDS}
        for key in DESIGN_FIELDS:
            c[key] = copy.deepcopy(DEFAULT[key])
    if raw.get('rck_layout_revision', 1) != 2:
        layouts = ([c] if c['design'] == 'RCK' else []) + ([c['design_presets']['RCK']] if 'RCK' in c['design_presets'] else [])
        for layout in layouts:
            if layout['x'] == 360 and layout['y'] == 36:
                layout.update(x=500, y=0)
            for key, old, new in [('players0', [60, 125, 100], [24, 190, 100]),
                                  ('players1', [1565, 125, 100], [1601, 190, 100]),
                                  ('focus', [76, 944, 100], [36, 925, 100]),
                                  ('boost', [1590, 775, 140], [1695, 860, 120])]:
                if layout['panels'][key] == old:
                    layout['panels'][key] = new
    return c


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.config = copy.deepcopy(DEFAULT)
        self.match = {'scores': [0, 0], 'time': 300, 'overtime': False,
                      'players': [], 'target': '', 'banner': ''}
        self.status = 'Conexión automática · esperando Rocket League'
        self.finished = set()
        self.banner_until = 0
        self.automatic = False
        self.last_update = 0
        self.playlist_id = None
        self.match_closed = False
        self.history_replay = False
        self.goal_sequence = 0
        self.goal_until = 0
        self.goal_team = 0
        self.goal_armed = True
        self.in_goal_replay = False

    def snapshot(self):
        with self.lock:
            if time.monotonic() > self.banner_until:
                self.match['banner'] = ''
            goal_remaining = max(0, int((self.goal_until-time.monotonic())*1000))
            return copy.deepcopy({'goal_effect': {'id': self.goal_sequence, 'remaining': goal_remaining,
                                                 'team': self.goal_team}, 'config': self.config, 'match': self.match,
                                  'overlay_visible': (self.playlist_id in PRIVATE_PLAYLISTS
                                      and (not self.match_closed or (goal_remaining > 0 and self.config['show_events']))
                                      and not self.history_replay
                                      and self.automatic and self.last_update > 0
                                      and time.monotonic()-self.last_update < 5),
                                  'series': series_state(self.config),
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
                # Missing/unknown playlist must never reveal the overlay.
                value = g.get('PlaylistId')
                self.playlist_id = int(value) if isinstance(value, (int, str)) and str(value).isdigit() else None
                for t in g.get('Teams', []):
                    i = t.get('TeamNum')
                    if i in (0, 1):
                        m['scores'][i] = max(0, int(t.get('Score', 0)))
                m['time'] = int(g.get('TimeSeconds', m['time']))
                m['overtime'] = bool(g.get('bOvertime', False))
                players = []
                for player in d.get('Players', []):
                    if not isinstance(player, dict) or player.get('TeamNum') not in (0, 1):
                        continue
                    player = dict(player)
                    # Live spectator packets omit Boost when it is zero. Only
                    # infer zero if spectator car telemetry is actually present.
                    if player.get('Boost') is None and any(key in player for key in
                            ('bHasCar', 'Speed', 'bBoosting', 'bOnGround', 'bOnWall', 'bDemolished')):
                        player['Boost'] = 0
                    players.append(player)
                m['players'] = players
                m['target'] = (g.get('Target') or {}).get('Name', '')
                self.last_update = time.monotonic()
            elif event == 'MatchCreated':
                self.goal_armed = True
                self.in_goal_replay = False
                self.goal_until = 0
                self.playlist_id = None
                self.match_closed = False
                self.history_replay = False
                m['players'], m['target'], m['banner'] = [], '', ''
            elif event == 'ReplayCreated':
                self.history_replay = True
                self.goal_until = 0
            elif event == 'ClockUpdatedSeconds':
                m['time'] = int(d.get('TimeSeconds', 0))
                m['overtime'] = bool(d.get('bOvertime', False))
            elif event == 'GoalReplayStart':
                self.in_goal_replay = True
                self.goal_armed = False
            elif event in ('GoalReplayEnd', 'GoalReplayWillEnd'):
                # Replay completion must not arm another celebration.
                self.in_goal_replay = False if event == 'GoalReplayEnd' else self.in_goal_replay
            elif event == 'RoundStarted':
                self.in_goal_replay = False
                self.goal_armed = True
            elif event == 'GoalScored':
                # No scorer message: only a three-second graphic transition.
                m['banner'] = ''
                if (self.config['show_events'] and self.playlist_id in PRIVATE_PLAYLISTS
                        and not self.history_replay and not self.match_closed
                        and self.goal_armed and not self.in_goal_replay):
                    self.goal_armed = False
                    self.goal_sequence += 1
                    self.goal_until = time.monotonic() + 3
                    scorer = d.get('Scorer') or {}
                    self.goal_team = scorer.get('TeamNum', 0) if scorer.get('TeamNum') in (0, 1) else 0
            elif event == 'MatchEnded':
                self.match_closed = True
                winner, guid = d.get('WinnerTeamNum'), d.get('MatchGuid')
                if winner in (0, 1):
                    m['banner'] = ''
                    if (self.config['auto_series'] and guid and guid not in self.finished
                            and self.playlist_id in PRIVATE_PLAYLISTS and not self.history_replay):
                        self.finished.add(guid)
                        if not series_state(self.config)['complete']:
                            self.config['teams'][winner]['wins'] += 1
                            self.config['game'] = series_state(self.config)['game']
            elif event == 'MatchDestroyed':
                self.goal_until = 0
                self.playlist_id = None
                self.match_closed = True
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
    snapshot['overlay_visible'] = True
    snapshot['match'] = {
        'scores': [2, 1], 'time': 193, 'overtime': False, 'target': 'PIRU', 'banner': '',
        'players': [{'Name': name, 'TeamNum': i//3, 'Boost': boost,
                     'Score': 541 if i == 0 else 125+i*32, 'Goals': 2 if i == 0 else i%2,
                     'Shots': 5, 'Assists': 1, 'Saves': 3}
                    for i, (name, boost) in enumerate([('PIRU', 72), ('CANDY', 38), ('FRESA', 100),
                                                      ('MANGO', 54), ('POP', 0), ('LIMÓN', 91)])]}
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
            elif route in ('/', '/overlay'):
                data = (ROOT / 'overlay.html').read_bytes()
                mime = 'text/html; charset=utf-8'
            elif route == '/boost-animation.js':
                data = (ROOT / 'boost-animation.js').read_bytes()
                mime = 'application/javascript; charset=utf-8'
            elif route in ('/assets/torneo.png', '/assets/discord.png'):
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
        self.connection = GameConnection(self.store)
        self.file = ROOT / 'ultimo_perfil.json'
        if self.file.exists():
            try:
                self.store.config = normalize_config(json.loads(self.file.read_text('utf-8')))
            except (ValueError, TypeError, KeyError):
                pass
        try:
            self.server = make_server(self.store, 18765)
        except OSError:
            self.server = make_server(self.store)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/overlay'
        root.title(f'Piruleta - Overlay {APP_VERSION}')
        root.geometry('1280x850')
        root.minsize(1050, 850)
        root.configure(bg='#12101a')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background='#201b2c', foreground='#f7effa', font=('Segoe UI', 10))
        style.configure('TEntry', fieldbackground='#30283d', foreground='white', insertcolor='white')
        style.configure('TSpinbox', fieldbackground='#30283d', foreground='white', arrowsize=14)
        style.configure('TCombobox', fieldbackground='#30283d', foreground='white')
        style.map('TCombobox', fieldbackground=[('readonly', '#30283d')], foreground=[('readonly', 'white')])
        style.configure('TButton', padding=(12, 8), background='#3e304a')
        style.configure('Control.TButton', padding=(10, 2))
        style.map('TButton', background=[('active', '#75435d')])
        style.configure('TNotebook.Tab', padding=(14, 10))
        # Keep actual BooleanVars and keyboard-accessible checkbuttons, with a tick instead of clam's X.
        self.check_images = []
        for checked in (False, True):
            indicator = tk.PhotoImage(master=root, width=20, height=20)
            indicator.put('#201b2c', to=(0, 0, 20, 20))
            indicator.put('#fa54b7' if checked else '#796685', to=(1, 1, 19, 19))
            indicator.put('#fa54b7' if checked else '#181426', to=(3, 3, 17, 17))
            if checked:
                for x in range(4, 16):
                    y = x+5 if x < 8 else 20-x
                    indicator.put('white', to=(x, y-1, x+2, y+2))
            self.check_images.append(indicator)
        style.element_create('Piruleta.Check.indicator', 'image', self.check_images[0],
                             ('selected', self.check_images[1]), sticky='')
        style.layout('Piruleta.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
            ('Piruleta.Check.indicator', {'side': 'left', 'sticky': ''}),
            ('Checkbutton.label', {'side': 'left', 'sticky': 'nswe'})]})])
        style.configure('Piruleta.TCheckbutton', padding=(0, 3), background='#201b2c')
        self.vars, self.team_vars = {}, [{}, {}]
        self.last_game = self.store.config['game']
        head = tk.Frame(root, bg='#12101a')
        head.pack(fill='x', padx=24, pady=(20, 12))
        tk.Label(head, text='Piruleta - Overlay', fg='#fa54b7', bg='#12101a', font=('Segoe UI', 23, 'bold')).pack(side='left')
        ttk.Button(head, text='Abrir vista previa', command=lambda: webbrowser.open(self.url+'?preview=1')).pack(side='right', padx=4)
        ttk.Button(head, text='Copiar URL para OBS', command=self.copy_url).pack(side='right', padx=4)
        body = ttk.Frame(root)
        body.pack(fill='both', expand=True, padx=24)
        left = ttk.Frame(body, padding=12)
        left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(body, padding=12, width=395)
        right.pack(side='right', fill='y')
        ttk.Label(left, text='DISEÑO EN DIRECTO', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.canvas = tk.Canvas(left, bg='#141720', height=240, highlightthickness=0)
        self.canvas.pack(fill='x', pady=(10, 12))
        self.canvas.bind('<Configure>', lambda e: self.draw())
        ttk.Label(left, text='Esquema del marcador · abre la vista previa para ver el diseño completo', font=('Segoe UI', 9)).pack(anchor='w')
        nb = ttk.Notebook(left)
        nb.pack(fill='both', expand=True, pady=12)
        teams, design, backgrounds, visibility, layout, advanced = (ttk.Frame(nb, padding=15) for _ in range(6))
        nb.add(teams, text='Textos')
        nb.add(design, text='Diseño')
        nb.add(backgrounds, text='Fondos')
        nb.add(visibility, text='Elementos')
        nb.add(layout, text='Posiciones')
        nb.add(advanced, text='CSS libre')
        self.palette_labels = {'dark': 'Fondo principal', 'pink': 'Equipo A', 'coral': 'Color central',
                               'yellow': 'Equipo B', 'text': 'Color del texto'}
        self.panel_color_vars = {}
        ttk.Label(backgrounds, text='Fondos vinculados a la paleta del marcador principal.').pack(anchor='w', pady=(0, 12))
        for key, label in [('boost0', 'Turbo · equipo A'), ('boost1', 'Turbo · equipo B'),
                           ('stats0', 'Estadísticas · equipo A'), ('stats1', 'Estadísticas · equipo B'),
                           ('players0', 'Jugadores equipo A'), ('players1', 'Jugadores equipo B')]:
            row = ttk.Frame(backgrounds)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=23).pack(side='left')
            var = tk.StringVar(value=self.palette_labels[self.store.config['panel_colors'][key]])
            self.panel_color_vars[key] = var
            selector = ttk.Combobox(row, textvariable=var, state='readonly', values=list(self.palette_labels.values()))
            selector.pack(side='left', fill='x', expand=True)
            selector.bind('<<ComboboxSelected>>', lambda event: self.apply())
        self.vars['scoreboard_gradient'] = tk.BooleanVar(value=self.store.config['scoreboard_gradient'])
        ttk.Checkbutton(backgrounds, text='  Fondo del marcador en degradado (desmarcado: plano)',
                        variable=self.vars['scoreboard_gradient'], command=self.apply,
                        style='Piruleta.TCheckbutton').pack(anchor='w', pady=6)
        ttk.Label(backgrounds, text='Al cambiar esos colores en Diseño, los fondos elegidos se actualizan también.',
                  wraplength=500, foreground='#b6a4c3').pack(anchor='w', pady=12)
        self.panel_vars = {}
        ttk.Label(layout, text='Panel                       X               Y          Escala %').pack(anchor='w')
        for key, label in [('players0', 'Jugadores A'), ('players1', 'Jugadores B'), ('focus', 'Estadísticas'), ('boost', 'Turbo'), ('banner', 'Avisos')]:
            row = ttk.Frame(layout)
            row.pack(fill='x', pady=5)
            ttk.Label(row, text=label, width=20).pack(side='left')
            values = []
            for j, value in enumerate(self.store.config['panels'][key]):
                var = tk.StringVar(value=str(value))
                ttk.Spinbox(row, from_=25 if j == 2 else 0, to=200 if j == 2 else 1920, width=7, textvariable=var).pack(side='left', padx=5)
                values.append(var)
            self.panel_vars[key] = values
        ttk.Label(advanced, text='Estilos propios para cualquier detalle del overlay (opcional).').pack(anchor='w')
        self.css = tk.Text(advanced, height=9, bg='#181426', fg='white', insertbackground='white', font=('Consolas', 10), wrap='word')
        self.css.pack(fill='both', expand=True, pady=8)
        self.css.insert('1.0', self.store.config['custom_css'])
        self.entry(teams, 'Nombre del torneo', 'event')
        self.entry(teams, 'Fase / ronda', 'round')
        self.entry(teams, 'Partido de la serie', 'game', numeric=(1, 99))
        for i in range(2):
            row = ttk.Frame(teams)
            row.pack(fill='x', pady=7)
            ttk.Label(row, text=f'Equipo {i+1}', width=20).pack(side='left')
            v = tk.StringVar(value=self.store.config['teams'][i]['name'])
            self.team_vars[i]['name'] = v
            ttk.Entry(row, textvariable=v).pack(side='left', fill='x', expand=True)
            ttk.Button(row, text='Escudo…', command=lambda i=i: self.logo(i)).pack(side='left', padx=4)
            ttk.Button(row, text='Quitar', command=lambda i=i: self.clear_logo(i)).pack(side='left')
        ttk.Button(teams, text='Cambiar equipos de lado', style='Control.TButton',
                   command=self.swap_teams).pack(anchor='e', pady=(6, 0))
        colorrow = ttk.Frame(design)
        colorrow.pack(fill='x', pady=5)
        for key, title in [('pink', 'Equipo A'), ('coral', 'Coral'), ('yellow', 'Equipo B'), ('dark', 'Fondo'), ('text', 'Texto')]:
            ttk.Button(colorrow, text=title, command=lambda k=key: self.color(k)).pack(side='left', padx=2)
        self.entry(design, 'Estilo', 'design', choices=['angular', 'rounded', 'classic'])
        self.entry(design, 'Tipografía', 'font', choices=['Arial', 'Segoe UI', 'Verdana', 'Trebuchet MS', 'Impact'])
        self.entry(design, 'Escala (%)', 'scale', numeric=(50, 150))
        self.entry(design, 'Opacidad (%)', 'opacity', numeric=(10, 100))
        self.entry(design, 'Posición horizontal', 'x', numeric=(0, 1900))
        self.entry(design, 'Posición vertical', 'y', numeric=(0, 1000))
        for k, label in [('show_logos', 'Escudos de equipos'), ('show_players', 'Turbo de todos los jugadores'), ('show_stats', 'Estadísticas del jugador en cámara'), ('show_boost', 'Turbo del jugador en cámara'), ('show_events', 'Cortina de gol'), ('auto_series', 'Sumar victorias automáticamente (API)')]:
            v = tk.BooleanVar(value=self.store.config[k])
            self.vars[k] = v
            ttk.Checkbutton(visibility, text='  '+label, variable=v, command=self.apply,
                            style='Piruleta.TCheckbutton').pack(anchor='w', pady=2)
        ttk.Button(visibility, text='Probar cortina de gol', style='Control.TButton',
                   command=lambda: webbrowser.open(self.url+'?preview=1&goal=1')).pack(anchor='w', pady=3)
        ttk.Button(left, text='Aplicar diseño', style='Control.TButton', command=self.apply).pack(anchor='e')
        ttk.Label(right, text='CONTROL DEL PARTIDO', font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=(0, 10))
        ttk.Label(right, text='Formato de la serie', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.format_var = tk.StringVar(value=f"BO{self.store.config['bestof']}")
        self.format_selector = ttk.Combobox(right, textvariable=self.format_var, state='readonly',
                                            values=[f'BO{n}' for n in SERIES_FORMATS])
        self.format_selector.pack(fill='x', pady=(6, 4))
        self.format_selector.bind('<<ComboboxSelected>>', self.change_format)
        self.series_hint = ttk.Label(right, wraplength=340, foreground='#ffce72')
        self.series_hint.pack(anchor='w', pady=(0, 10))
        self.score_labels, self.win_labels = [], []
        for i in range(2):
            ttk.Label(right, text=f'EQUIPO {i+1} · GOLES / SERIE').pack(anchor='w', pady=(12, 4))
            row = ttk.Frame(right)
            row.pack(fill='x')
            label = ttk.Label(row, text='0', font=('Segoe UI', 25, 'bold'), width=3, anchor='center')
            label.pack(side='left', padx=8)
            self.score_labels.append(label)
            label = ttk.Label(row, text='Serie 0', width=7, anchor='center')
            label.pack(side='left', padx=4)
            self.win_labels.append(label)
            ttk.Button(row, text='−', width=3, style='Control.TButton', command=lambda i=i: self.win(i, -1)).pack(side='left')
            ttk.Button(row, text='+', width=3, style='Control.TButton', command=lambda i=i: self.win(i, 1)).pack(side='left')
        ttk.Label(right, text='Tiempo y prórroga: sincronizados por la API.',
                  wraplength=340, foreground='#b6a4c3').pack(anchor='w', pady=(14, 8))
        ttk.Button(right, text='Reiniciar serie', style='Control.TButton', command=self.reset_series).pack(fill='x', pady=3)
        ttk.Separator(right).pack(fill='x', pady=10)
        ttk.Button(right, text='Guardar perfil…', style='Control.TButton', command=self.save).pack(fill='x', pady=3)
        ttk.Button(right, text='Cargar perfil…', style='Control.TButton', command=self.load).pack(fill='x', pady=3)
        self.status = tk.Label(root, bg='#12101a', fg='#ffce72', anchor='w', padx=24, pady=13)
        self.status.pack(side='bottom', fill='x', before=body)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.connect()
        self.refresh()

    def entry(self, parent, title, key, numeric=None, choices=None):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=title, width=23).pack(side='left')
        v = tk.StringVar(value=str(self.store.config[key]))
        self.vars[key] = v
        if numeric:
            w = ttk.Spinbox(row, from_=numeric[0], to=numeric[1], textvariable=v, width=10)
        elif choices:
            w = ttk.Combobox(row, values=choices, textvariable=v, state='readonly')
            w.bind('<<ComboboxSelected>>', lambda e: self.apply())
        else:
            w = ttk.Entry(row, textvariable=v)
        w.pack(side='left', fill='x', expand=True)
        w.bind('<Return>', lambda e: self.apply())
        return w

    @staticmethod
    def font_choices():
        imported = sorted(
            CUSTOM_FONT_PREFIX + path.name
            for path in FONT_DIRECTORY.glob('*')
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in FONT_TYPES
        )
        return (*STANDARD_FONTS, *imported)

    def import_font(self):
        filename = filedialog.askopenfilename(
            parent=self.root, title='Importar tipografía',
            filetypes=[('Fuentes', '*.ttf *.otf *.woff *.woff2')],
        )
        if not filename:
            return
        source = Path(filename)
        extension = source.suffix.lower()
        try:
            if extension not in FONT_TYPES:
                raise ValueError('Elige un archivo TTF, OTF, WOFF o WOFF2.')
            with source.open('rb') as file:
                data = file.read(MAX_FONT_BYTES + 1)
            if len(data) > MAX_FONT_BYTES or not data.startswith(FONT_TYPES[extension][1]):
                raise ValueError('La fuente debe tener un formato válido y ocupar como máximo 16 MB.')
            FONT_DIRECTORY.mkdir(parents=True, exist_ok=True)
            stem = source.stem[:80]
            target = FONT_DIRECTORY / (stem + extension)
            number = 2
            while target.exists():
                target = FONT_DIRECTORY / f'{stem} ({number}){extension}'
                number += 1
            with target.open('xb') as file:
                file.write(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror('No se pudo importar la tipografía', str(exc), parent=self.root)
            return
        self.font_selector.configure(values=self.font_choices())
        self.vars['font'].set(CUSTOM_FONT_PREFIX + target.name)
        self.apply()

    def apply(self):
        try:
            with self.store.lock:
                raw = copy.deepcopy(self.store.config)
                for k, v in self.vars.items():
                    raw[k] = v.get()
                for i in range(2):
                    raw['teams'][i]['name'] = self.team_vars[i]['name'].get()
                raw['panels'] = {k: [v.get() for v in values] for k, values in self.panel_vars.items()}
                raw['custom_css'] = self.css.get('1.0', 'end-1c')
                palette_keys = {label: key for key, label in self.palette_labels.items()}
                raw['panel_colors'] = {key: palette_keys[var.get()] for key, var in self.panel_color_vars.items()}
                for key, field in getattr(self, 'color_vars', {}).items():
                    color = re.fullmatch(r'#?([0-9a-fA-F]{6})', field.get().strip())
                    if not color:
                        raise ValueError(f'{self.palette_labels[key]}: escribe un color hexadecimal de seis dígitos, como #FA54B7.')
                    raw['colors'][key] = '#' + color[1].upper()
                previous = self.store.config['design']
                raw = switch_design(raw, previous)
                self.store.config = normalize_config(raw)
            if (previous == 'RCK') != (raw['design'] == 'RCK'):
                self.sync()
            else:
                self.draw()
            return True
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Revisa el diseño', str(exc))
            return False

    def sync(self):
        c = self.store.config
        self.format_var.set(f"BO{c['bestof']}")
        for k, v in self.vars.items():
            v.set(c[k])
        for key, var in self.panel_color_vars.items():
            var.set(self.palette_labels[c['panel_colors'][key]])
        for i in range(2):
            self.team_vars[i]['name'].set(c['teams'][i]['name'])
        for k, values in self.panel_vars.items():
            for j, v in enumerate(values):
                v.set(c['panels'][k][j])
        self.css.delete('1.0', 'end')
        self.css.insert('1.0', c['custom_css'])
        self.draw()

    def color(self, key):
        dialog = tk.Toplevel(self.root, bg='#201b2c')
        dialog.title('Elegir color')
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        value = tk.StringVar(dialog, value=self.store.config['colors'][key])
        ttk.Label(frame, text='Color hexadecimal').pack(anchor='w')
        field = ttk.Entry(frame, textvariable=value, width=22)
        field.pack(fill='x', pady=(5, 8))
        error = ttk.Label(frame, foreground='#ffce72')
        error.pack(anchor='w')

        def apply_color(event=None):
            match = re.fullmatch(r'#?([0-9a-fA-F]{6})', value.get().strip())
            if not match:
                error.configure(text='Escribe seis dígitos, por ejemplo #BEB4E6.')
                field.focus_set()
                return
            with self.store.lock:
                self.store.config['colors'][key] = '#' + match[1].upper()
            dialog.destroy()

        def choose_color():
            initial = value.get().strip()
            if re.fullmatch(r'#?[0-9a-fA-F]{6}', initial):
                initial = '#' + initial.lstrip('#')
            else:
                initial = self.store.config['colors'][key]
            selected = colorchooser.askcolor(initial, parent=dialog)[1]
            if selected:
                value.set(selected)
                error.configure(text='')

        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(8, 0))
        ttk.Button(buttons, text='Selector visual…', command=choose_color).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='Cancelar', command=dialog.destroy).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='Aplicar', command=apply_color).pack(side='right')
        dialog.bind('<Return>', apply_color)
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        dialog.wait_visibility()
        dialog.grab_set()
        field.focus_set()
        field.selection_range(0, 'end')

    def logo(self, i):
        import base64
        path = filedialog.askopenfilename(filetypes=[('Imagen PNG / JPG', '*.png *.jpg *.jpeg')])
        if path:
            data = Path(path).read_bytes()
            if len(data) > MAX_LOGO_BYTES:
                messagebox.showerror('Imagen grande', 'El tamaño máximo del escudo es de 4 MB.')
                return
            mime = 'image/png' if Path(path).suffix.lower() == '.png' else 'image/jpeg'
            with self.store.lock:
                self.store.config['teams'][i]['logo'] = f'data:{mime};base64,' + base64.b64encode(data).decode()

    def clear_logo(self, i):
        with self.store.lock:
            self.store.config['teams'][i]['logo'] = ''

    def swap_teams(self):
        if not self.apply():
            return
        with self.store.lock:
            self.store.config = swap_team_sides(self.store.config)
        self.sync()

    def win(self, i, delta):
        with self.store.lock:
            state = series_state(self.store.config)
            if delta > 0 and state['complete']:
                return
            t = self.store.config['teams'][i]
            t['wins'] = max(0, min(self.store.config['bestof']//2+1, t['wins']+delta))
            self.store.config['game'] = series_state(self.store.config)['game']
            if 'game' in self.vars:
                self.vars['game'].set(str(self.store.config['game']))
        self.draw()

    def change_format(self, event=None):
        bestof = int(self.format_var.get()[2:])
        with self.store.lock:
            raw = copy.deepcopy(self.store.config)
            raw['bestof'] = bestof
            try:
                if (sum(t['wins'] for t in raw['teams']) > bestof or
                        max(t['wins'] for t in raw['teams']) > bestof//2+1):
                    raise ValueError('El resultado no cabe en este formato.')
                updated = normalize_config(raw)
            except ValueError:
                self.format_var.set(f"BO{self.store.config['bestof']}")
                messagebox.showinfo('Formato de la serie',
                                    'Reinicia la serie antes de elegir un formato menor que el resultado actual.')
                return
            self.store.config = updated
            if 'game' in self.vars:
                self.vars['game'].set(str(updated['game']))
        self.draw()

    def reset_series(self):
        with self.store.lock:
            for team in self.store.config['teams']:
                team['wins'] = 0
            self.store.config['game'] = 1
        self.vars['game'].set('1')
        self.draw()

    def connect(self):
        self.connection.connect(self.store.config['api_port'])

    def copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url)
        messagebox.showinfo('URL copiada', self.url+'\n\nOBS → Fuente de navegador → 1920 × 1080.\nMantén Piruleta - Overlay abierto.')

    def save(self):
        if not self.apply():
            return
        path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Perfil Piruleta', '*.json')])
        if path:
            Path(path).write_text(json.dumps(self.store.snapshot()['config'], ensure_ascii=False, indent=2), 'utf-8')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Perfil Piruleta', '*.json')])
        if path:
            try:
                c = normalize_config(json.loads(Path(path).read_text('utf-8')))
                previous_port = self.store.config['api_port']
                with self.store.lock:
                    self.store.config = c
                self.sync()
                if c['api_port'] != previous_port:
                    self.connect()
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                messagebox.showerror('No se pudo cargar', str(exc))

    def draw(self):
        if not hasattr(self, 'canvas'):
            return
        canvas = self.canvas
        canvas.delete('all')
        w = max(600, canvas.winfo_width())
        s = self.store.snapshot()
        c, m = s['config'], s['match']
        a, b = c['colors']['pink'], c['colors']['yellow']
        canvas.create_text(w/2, 30, text=c['event'], fill='#b6a4c3', font=('Segoe UI', 10, 'bold'))
        canvas.create_rectangle(25, 57, w/2-48, 115, fill=a, outline='')
        canvas.create_rectangle(w/2+48, 57, w-25, 115, fill=b, outline='')
        canvas.create_rectangle(w/2-48, 57, w/2+48, 115, fill='white', outline='')
        for i in range(2):
            x = 40 if i == 0 else w-40
            canvas.create_text(x, 85, text=c['teams'][i]['name'][:19], fill='#181426', anchor='w' if i==0 else 'e', font=('Segoe UI', 12, 'bold'))
            canvas.create_text(w/2 + (-75 if i==0 else 75), 85, text=m['scores'][i], fill='#181426', font=('Segoe UI', 24, 'bold'))
        sec = abs(int(m['time']))
        clock = ('+' if m['overtime'] else '')+f'{sec//60}:{sec%60:02}'
        canvas.create_text(w/2, 85, text=clock, fill='#181426', font=('Segoe UI', 19, 'bold'))
        canvas.create_text(w/2, 136, text=f"{c['round']} · PARTIDO {c['game']} · BO{c['bestof']}", fill='white', font=('Segoe UI', 9))
        for i in range(2):
            self.score_labels[i].configure(text=str(m['scores'][i]))
            self.win_labels[i].configure(text=f"Serie {c['teams'][i]['wins']}")
        state = series_state(c)
        hint = f"BO{c['bestof']} · {state['target']} victorias para ganar"
        if c['bestof'] % 2 == 0:
            hint += f" · hasta {c['bestof']} partidos; admite empate"
        if state['complete']:
            hint += ' · EMPATE' if state['tied'] else ' · SERIE FINALIZADA'
        self.series_hint.configure(text=hint)

    def refresh(self):
        if self.store.config['game'] != self.last_game:
            self.last_game = self.store.config['game']
            self.vars['game'].set(str(self.last_game))
        self.status.configure(text='● '+self.store.status+'     |     OBS: '+self.url)
        self.draw()
        self.root.after(250, self.refresh)

    def close(self):
        if self.apply():
            self.file.write_text(json.dumps(self.store.snapshot()['config'], ensure_ascii=False, indent=2), 'utf-8')
        self.connection.disconnect()
        self.server.shutdown()
        self.root.destroy()


if __name__ == '__main__':
    App(tk.Tk()).root.mainloop()
