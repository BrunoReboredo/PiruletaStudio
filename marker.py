"""Full standalone Overlay controls, embedded in Studio's shared state."""
import copy
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from vendor.overlay.app import App as OverlayApp, SERIES_FORMATS


class MarkerPanel(OverlayApp):
    def __init__(self, parent, owner):
        self.owner = owner
        self.root = owner.root
        self.store = owner.store
        self.connection = owner.game
        self.vars, self.team_vars = {}, [{}, {}]
        self.last_game = self.store.config['game']
        head = tk.Frame(parent, bg='#12101a')
        head.pack(fill='x', padx=4, pady=(20, 12))
        tk.Label(head, text='Marcador en directo', fg='#fa54b7', bg='#12101a', font=('Segoe UI', 23, 'bold')).pack(side='left')
        body = ttk.Frame(parent)
        body.pack(fill='both', expand=True, padx=4)
        left = ttk.Frame(body, padding=12)
        left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(body, padding=12, width=300)
        right.pack(side='right', fill='y')
        ttk.Label(left, text='DISEÑO EN DIRECTO', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.canvas = tk.Canvas(left, bg='#141720', height=155, highlightthickness=0)
        self.canvas.pack(fill='x', pady=(10, 12))
        self.canvas.bind('<Configure>', lambda e: self.draw())
        ttk.Label(left, text='Esquema del marcador', font=('Segoe UI', 9)).pack(anchor='w')
        nb = ttk.Notebook(left)
        self.design_tabs = nb
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
        for key, label in [('boost', 'Indicador de turbo'), ('stats', 'Caja de estadísticas'),
                           ('players0', 'Jugadores equipo A'), ('players1', 'Jugadores equipo B')]:
            row = ttk.Frame(backgrounds)
            row.pack(fill='x', pady=6)
            ttk.Label(row, text=label, width=20).pack(side='left')
            var = tk.StringVar(value=self.palette_labels[self.store.config['panel_colors'][key]])
            self.panel_color_vars[key] = var
            selector = ttk.Combobox(row, textvariable=var, state='readonly', values=list(self.palette_labels.values()))
            selector.pack(side='left', fill='x', expand=True)
            selector.bind('<<ComboboxSelected>>', lambda event: self.apply())
        ttk.Label(backgrounds, text='Al cambiar esos colores en Diseño, los fondos elegidos se actualizan también.',
                  wraplength=500, foreground='#b6a4c3').pack(anchor='w', pady=12)
        self.panel_vars = {}
        ttk.Label(layout, text='Panel                       X               Y          Escala %').pack(anchor='w')
        for key, label in [('players0', 'Jugadores A'), ('players1', 'Jugadores B'), ('focus', 'Estadísticas'), ('boost', 'Turbo'), ('brand', 'Marca'), ('banner', 'Avisos')]:
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
        for k, label in [('show_logos', 'Escudos de equipos'), ('show_players', 'Turbo de todos los jugadores'), ('show_stats', 'Estadísticas del jugador en cámara'), ('show_boost', 'Turbo del jugador en cámara'), ('show_brand', 'Marca del torneo'), ('show_events', 'Aviso de victoria'), ('auto_series', 'Sumar victorias automáticamente (API)')]:
            v = tk.BooleanVar(value=self.store.config[k])
            self.vars[k] = v
            ttk.Checkbutton(visibility, text='  '+label, variable=v, command=self.apply,
                            style='TCheckbutton').pack(anchor='w', pady=5)
        ttk.Button(left, text='Aplicar diseño', style='Control.TButton', command=self.apply).pack(anchor='e')
        ttk.Label(right, text='CONTROL DEL PARTIDO', font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=(0, 10))
        ttk.Label(right, text='Formato de la serie', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.format_var = tk.StringVar(value=f"BO{self.store.config['bestof']}")
        self.format_selector = ttk.Combobox(right, textvariable=self.format_var, state='readonly',
                                            values=[f'BO{n}' for n in SERIES_FORMATS])
        self.format_selector.pack(fill='x', pady=(6, 4))
        self.format_selector.bind('<<ComboboxSelected>>', self.change_format)
        self.series_hint = ttk.Label(right, wraplength=270, foreground='#ffce72')
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
                  wraplength=270, foreground='#b6a4c3').pack(anchor='w', pady=(14, 8))
        ttk.Button(right, text='Reiniciar serie', style='Control.TButton', command=self.reset_series).pack(fill='x', pady=3)
        ttk.Separator(right).pack(fill='x', pady=10)
        ttk.Button(right, text='Guardar perfil…', style='Control.TButton', command=self.save).pack(fill='x', pady=3)
        ttk.Button(right, text='Cargar perfil…', style='Control.TButton', command=self.load).pack(fill='x', pady=3)

        api = ttk.LabelFrame(parent, text='Conexión de Rocket League')
        api.pack(fill='x', padx=4, pady=10)
        ttk.Label(api, text='Puerto de la Stats API').pack(side='left')
        ttk.Entry(api, textvariable=owner.vars['api_port'], width=9).pack(side='left', padx=8)
        ttk.Button(api, text='Reconectar', command=self.reconnect).pack(side='left')
        ttk.Label(api, text='Una sola conexión para marcador y estadísticas.').pack(side='left', padx=12)

    def apply(self):
        shorts = [team.get('short', '') for team in self.store.config['teams']]
        if not super().apply():
            return False
        with self.store.lock:
            for team, short in zip(self.store.config['teams'], shorts):
                team['short'] = short
        self.owner.note.set('Marcador actualizado. Las animaciones conservan los equipos de la preparación.')
        return True

    def swap_teams(self):
        if self.apply():
            self.store.swap_marker_sides()
            self.sync()
            self.owner.note.set('Equipos de lado intercambiados. La victoria preparada sigue al equipo correcto.')

    def reset_series(self):
        self.store.reset_series()
        self.sync()
        self.owner.note.set('Serie reiniciada. Las animaciones preparadas se conservan.')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Perfil Piruleta', '*.json')])
        if path:
            try:
                previous = self.store.config['api_port']
                self.store.set_marker(json.loads(Path(path).read_text(encoding='utf-8-sig')))
                self.sync()
                self.owner.vars['api_port'].set(str(self.store.config['api_port']))
                if previous != self.store.config['api_port']:
                    self.connection.connect(self.store.config['api_port'])
                self.owner.note.set('Perfil de marcador cargado. No modifica los vídeos preparados.')
            except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
                messagebox.showerror('No se pudo cargar el marcador', str(exc), parent=self.root)

    def reconnect(self):
        try:
            port = int(self.owner.vars['api_port'].get())
            if not 1 <= port <= 65535:
                raise ValueError('Puerto fuera de rango.')
            with self.store.lock:
                self.store.config['api_port'] = port
            self.connection.connect(port)
        except Exception as exc:
            self.owner.error(exc)

    def refresh(self):
        if self.store.config['game'] != self.last_game:
            self.last_game = self.store.config['game']
            self.vars['game'].set(str(self.last_game))
        self.draw()
