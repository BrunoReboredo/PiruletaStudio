"""Full standalone Overlay controls, embedded in Studio's shared state."""
import copy
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from vendor.overlay.app import App as OverlayApp, SERIES_FORMATS


def install_check_style(root, style):
    images = []
    for selected in (False, True):
        image = tk.PhotoImage(master=root, width=18, height=18)
        image.put('#b6a4c3', to=(0, 0, 18, 18))
        image.put('#e749a0' if selected else '#100e18', to=(1, 1, 17, 17))
        if selected:
            for x, y in [(4, 9), (5, 10), (6, 11), (7, 12), (8, 11), (9, 10), (10, 9), (11, 8), (12, 7), (13, 6)]:
                image.put('#ffffff', to=(x, y, x+2, y+2))
        images.append(image)
    root.marker_check_images = images
    style.element_create('Marker.indicator', 'image', images[0], ('selected', images[1]))
    style.layout('Marker.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Marker.indicator', {'side': 'left', 'sticky': ''}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
            ('Checkbutton.label', {'sticky': 'nswe'})]})]})])


class MarkerPanel(OverlayApp):
    def __init__(self, parent, owner):
        self.owner = owner
        self.root = owner.root
        self.store = owner.store
        self.connection = owner.game
        self.vars, self.team_vars = {}, [{}, {}]
        head = tk.Frame(parent, bg='#12101a')
        head.pack(fill='x', padx=4, pady=(20, 12))
        tk.Label(head, text='Marcador en directo', fg='#fa54b7', bg='#12101a', font=('Segoe UI', 23, 'bold')).pack(side='left')
        body = ttk.Frame(parent)
        body.pack(fill='both', expand=True, padx=4)
        left = ttk.Frame(body, padding=12)
        left.pack(fill='both', expand=True)
        nb = ttk.Notebook(left)
        self.design_tabs = nb
        nb.pack(fill='both', expand=True, pady=12)
        teams, design, backgrounds, visibility, cameras, layout, advanced = (ttk.Frame(nb, padding=15) for _ in range(7))
        nb.add(teams, text='Ajustes')
        nb.add(design, text='Diseño')
        nb.add(backgrounds, text='Fondos')
        nb.add(visibility, text='Elementos')
        nb.add(cameras, text='Cámaras')
        nb.add(layout, text='Posiciones')
        nb.add(advanced, text='CSS libre')
        self.palette_labels = {'dark': 'Fondo principal', 'pink': 'Equipo A', 'coral': 'Color central',
                               'yellow': 'Equipo B', 'text': 'Color del texto'}
        self.panel_color_vars = {}
        ttk.Label(backgrounds, text='Fondos vinculados a la paleta del marcador principal.').pack(anchor='w', pady=(0, 12))
        for key, label in [('boost0', 'Turbo equipo A'), ('boost1', 'Turbo equipo B'),
                           ('stats0', 'Estadísticas equipo A'), ('stats1', 'Estadísticas equipo B'),
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
        self.vars['scoreboard_gradient'] = tk.BooleanVar(value=self.store.config['scoreboard_gradient'])
        ttk.Checkbutton(backgrounds, text='Fondo del marcador en degradado (desmarcado: plano)',
                        variable=self.vars['scoreboard_gradient'], command=self.apply, style='Marker.TCheckbutton').pack(anchor='w', pady=8)
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
        ttk.Label(teams, text='Información del partido', font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(0, 12))
        match_info = ttk.Frame(teams)
        match_info.pack(fill='x')
        for column, weight in enumerate((1, 3, 4)):
            match_info.columnconfigure(column, weight=weight, uniform='matchinfo' if column > 0 else '')
        format_box = ttk.Frame(match_info)
        format_box.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        ttk.Label(format_box, text='Formato de la serie').pack(anchor='w', pady=(0, 5))
        self.format_var = tk.StringVar(value=f"BO{self.store.config['bestof']}")
        self.format_selector = ttk.Combobox(format_box, textvariable=self.format_var, state='readonly',
                                          values=[f'BO{n}' for n in SERIES_FORMATS], width=7)
        self.format_selector.pack(fill='x')
        self.format_selector.bind('<<ComboboxSelected>>', self.change_format)
        for column, key, title in [(1, 'round', 'Texto de abajo'), (2, 'event', 'Texto de arriba')]:
            box = ttk.Frame(match_info)
            box.grid(row=0, column=column, sticky='nsew', padx=(0, 8) if column == 1 else 0)
            ttk.Label(box, text=title).pack(anchor='w', pady=(0, 5))
            self.vars[key] = tk.StringVar(value=self.store.config[key])
            field = ttk.Entry(box, textvariable=self.vars[key], width=15)
            field.pack(fill='x', expand=True)
            field.bind('<Return>', lambda event: self.apply())
        ttk.Separator(teams).pack(fill='x', pady=10)
        team_actions = ttk.Frame(teams)
        team_actions.pack(fill='x')
        style = ttk.Style(self.root)
        for style_name, color in [('ResetSeries', '#1675bb'), ('SwapTeams', '#198f86'), ('ClearTeams', '#bc0060')]:
            style.configure(style_name+'.TButton', background=color, foreground='white', padding=(12, 12))
            style.map(style_name+'.TButton', background=[('active', color)])
        for column, text, command, button_style in [
                (0, 'Reiniciar serie', self.reset_series, 'ResetSeries.TButton'),
                (1, 'Cambiar equipos de lado', self.swap_teams, 'SwapTeams.TButton'),
                (2, 'Borrar nombres y escudos', self.clear_teams, 'ClearTeams.TButton')]:
            team_actions.columnconfigure(column, weight=1, uniform='teamactions')
            ttk.Button(team_actions, text=text, command=command, style=button_style).grid(
                row=0, column=column, sticky='ew', padx=(0, 10) if column < 2 else 0)
        team_columns = ttk.Frame(teams)
        team_columns.pack(fill='both', expand=True, pady=(53, 0))
        self.score_labels, self.win_labels, self.logo_labels = [], [], []
        self.logo_images, self.logo_sources = {}, {}
        for i, title in enumerate(('Equipo azul', 'Equipo naranja')):
            team_columns.columnconfigure(i, weight=1, uniform='teams')
            card = ttk.LabelFrame(team_columns, text=title.upper(), padding=20)
            card.grid(row=0, column=i, sticky='nsew', padx=(0, 12) if i == 0 else (12, 0))
            series_row = ttk.Frame(card)
            series_row.pack(fill='x', pady=(0, 18))
            score_box = ttk.Frame(series_row)
            score_box.pack(side='left', fill='x', expand=True)
            ttk.Label(score_box, text='Victorias de serie', foreground='#b6a4c3').pack(anchor='w')
            controls = ttk.Frame(score_box)
            controls.pack(anchor='w', pady=(4, 0))
            label = ttk.Label(controls, text='Serie 0', font=('Segoe UI', 15, 'bold'), width=9)
            label.pack(side='left')
            self.win_labels.append(label)
            ttk.Button(controls, text='−', width=3, style='Control.TButton', command=lambda i=i: self.win(i, -1)).pack(side='left', padx=(0, 4))
            ttk.Button(controls, text='+', width=3, style='Control.TButton', command=lambda i=i: self.win(i, 1)).pack(side='left')
            logo_label = ttk.Label(series_row, text='Sin escudo', anchor='center', width=12)
            logo_label.pack(side='right', padx=(12, 0))
            self.logo_labels.append(logo_label)
            ttk.Label(card, text='Nombre del equipo').pack(anchor='w')
            variable = tk.StringVar(value=self.store.config['teams'][i]['name'])
            self.team_vars[i]['name'] = variable
            ttk.Entry(card, textvariable=variable).pack(fill='x', pady=(7, 16))
            logo_actions = ttk.Frame(card)
            logo_actions.pack(fill='x')
            ttk.Button(logo_actions, text='Subir escudo…', command=lambda i=i: self.logo(i)).pack(side='left', fill='x', expand=True, padx=(0, 8))
            ttk.Button(logo_actions, text='Quitar escudo', command=lambda i=i: self.clear_logo(i)).pack(side='left')
            goals = ttk.Frame(card)
            goals.pack(fill='x', pady=(12, 0))
            ttk.Label(goals, text='Goles del partido · API', foreground='#b6a4c3').pack(side='left')
            label = ttk.Label(goals, text='0', font=('Segoe UI', 18, 'bold'))
            label.pack(side='right')
            self.score_labels.append(label)
        self.series_hint = ttk.Label(teams, foreground='#ffce72', anchor='center')
        self.series_hint.pack(fill='x', pady=(14, 4))
        self.series_hint.bind('<Configure>', lambda event: self.series_hint.configure(wraplength=max(100, event.width)))
        ttk.Label(teams, text='[GAME]: partido actual · [SERIE]: formato de la serie. Tiempo y goles sincronizados por la API.',
                  foreground='#b6a4c3', anchor='center').pack(fill='x', pady=(0, 16))
        ttk.Label(design, text='Colores del marcador y las estadísticas. Las animaciones conservan los colores de Datos de los equipos.',
                  wraplength=500, foreground='#b6a4c3').pack(anchor='w', pady=(0, 10))
        colorrow = ttk.Frame(design)
        colorrow.pack(fill='x', pady=5)
        self.color_vars = {}
        for column, (key, title) in enumerate(self.palette_labels.items()):
            value = tk.StringVar(value=self.store.config['colors'][key])
            self.color_vars[key] = value
            ttk.Label(colorrow, text=title).grid(row=0, column=column, sticky='w', padx=4)
            field = ttk.Entry(colorrow, textvariable=value, width=10)
            field.grid(row=1, column=column, sticky='ew', padx=4)
            field.bind('<Return>', lambda event: self.apply())
        self.entry(design, 'Estilo', 'design', choices=['angular', 'rounded', 'classic', 'RCK'])
        self.font_selector = self.entry(design, 'Tipografía', 'font', choices=self.font_choices())
        ttk.Button(design, text='Importar tipografía…', command=self.import_font).pack(anchor='e')
        self.entry(design, 'Escala (%)', 'scale', numeric=(50, 150))
        self.entry(design, 'Opacidad (%)', 'opacity', numeric=(10, 100))
        self.entry(design, 'Posición horizontal', 'x', numeric=(0, 1900))
        self.entry(design, 'Posición vertical', 'y', numeric=(0, 1000))
        for k, label in [('show_logos', 'Escudos de equipos'), ('show_players', 'Turbo de todos los jugadores'), ('show_stats', 'Estadísticas del jugador en cámara'), ('show_boost', 'Turbo del jugador en cámara'), ('show_events', 'Cortina de gol'), ('show_goal_replay', 'Barra de repetición de gol'), ('auto_series', 'Sumar victorias automáticamente (API)')]:
            v = tk.BooleanVar(value=self.store.config[k])
            self.vars[k] = v
            ttk.Checkbutton(visibility, text='  '+label, variable=v, command=self.apply,
                            style='Marker.TCheckbutton').pack(anchor='w', pady=5)
        for key, label in [('show_stats_camera', 'Cámara estadísticas'),
                           ('show_players_cameras', 'Cámaras turbos'),
                           ('auto_replay_cameras', 'Mostrar cámaras turbos durante 6,5 s al terminar la repetición')]:
            variable = tk.BooleanVar(value=self.store.config[key])
            self.vars[key] = variable
            ttk.Checkbutton(cameras, text='  '+label, variable=variable, command=lambda key=key: self.change_camera_mode(key),
                            style='Marker.TCheckbutton').pack(anchor='w', pady=5)
        ttk.Separator(cameras).pack(fill='x', pady=12)
        ttk.Label(cameras, text='Nombre del jugador en Rocket League y enlace de visualización OBS Ninja / VDO.Ninja.',
                  wraplength=600).pack(anchor='w', pady=(0, 8))
        camera_fields = ttk.Frame(cameras)
        camera_fields.pack(fill='both', expand=True)
        camera_fields.columnconfigure(1, weight=1)
        ttk.Label(camera_fields, text='Jugador').grid(row=0, column=0, sticky='w')
        ttk.Label(camera_fields, text='Enlace (?view=...)').grid(row=0, column=1, sticky='w')
        self.camera_vars = []
        for index in range(8):
            camera = self.store.config['cameras'][index] if index < len(self.store.config['cameras']) else {}
            name = tk.StringVar(value=camera.get('name', ''))
            url = tk.StringVar(value=camera.get('url', ''))
            ttk.Entry(camera_fields, textvariable=name, width=22).grid(row=index+1, column=0, sticky='ew', padx=(0, 10), pady=5)
            ttk.Entry(camera_fields, textvariable=url, width=35).grid(row=index+1, column=1, sticky='ew', pady=5)
            self.camera_vars.append((name, url))
        self.entry(visibility, 'Estilo de cortina', 'goal_style', choices=['Torneo Piruleta', 'Bigness League', 'RCS', 'RCK'])
        ttk.Button(visibility, text='Probar cortina de gol', command=self.preview_goal).pack(anchor='w', pady=6)
        actions = ttk.Frame(left, padding=(0, 12))
        actions.pack(side='bottom', fill='x', before=nb)
        for title, command in [('Aplicar diseño', self.apply), ('Guardar perfil…', self.save), ('Cargar perfil…', self.load)]:
            ttk.Button(actions, text=title, command=command, style='Control.TButton').pack(side='left', fill='x', expand=True, padx=4)
        def fit_tabs(event):
            tab_width = max(8, int((event.width - 42) / (7 * 8)))
            ttk.Style(self.root).configure('Marker.TNotebook.Tab', width=tab_width, anchor='center', padding=(4, 12))
        nb.configure(style='Marker.TNotebook')
        nb.bind('<Configure>', fit_tabs)

        api = ttk.LabelFrame(parent, text='Conexión de Rocket League')
        api.pack(fill='x', padx=4, pady=10)
        ttk.Label(api, text='Puerto de la Stats API').pack(side='left')
        ttk.Entry(api, textvariable=owner.vars['api_port'], width=9).pack(side='left', padx=8)
        ttk.Button(api, text='Reconectar', command=self.reconnect).pack(side='left')
        ttk.Label(api, text='Una sola conexión para marcador y estadísticas.').pack(side='left', padx=12)

    def apply(self):
        if not super().apply():
            return False
        self.sync_colors()
        self.owner.note.set('Marcador actualizado. Las animaciones conservan los equipos de la preparación.')
        return True

    def clear_teams(self):
        for team in self.team_vars:
            team['name'].set('')
        with self.store.lock:
            for team in self.store.config['teams']:
                team['logo'] = ''
        self.apply()

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

    def preview_goal(self):
        import webbrowser
        from urllib.parse import urlencode
        styles = {'Torneo Piruleta': 'piruleta', 'Bigness League': 'bigness', 'RCS': 'rcs', 'RCK': 'rck'}
        query = urlencode(dict(preview=1, goal=1, curtain=styles[self.vars['goal_style'].get()]))
        webbrowser.open(self.owner.url + '/overlay?' + query)

    def sync_colors(self):
        for key, value in self.color_vars.items():
            value.set(self.store.config['colors'][key])

    def sync(self):
        super().sync()
        self.sync_colors()
        for index, (name, url) in enumerate(self.camera_vars):
            camera = self.store.config['cameras'][index] if index < len(self.store.config['cameras']) else {}
            name.set(camera.get('name', ''))
            url.set(camera.get('url', ''))
        self.owner.refresh_metric_controls()
        if hasattr(self.owner,'mvp_delay'):
            self.owner.mvp_delay.set(str(self.store.config.get('mvp_delay',3)))

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

    def draw(self):
        self.refresh_match_controls()

    def refresh(self):
        self.refresh_match_controls()

    def refresh_match_controls(self):
        snapshot = self.store.snapshot()
        c, m = snapshot['config'], snapshot['match']
        for i in range(2):
            source = c['teams'][i]['logo']
            if self.logo_sources.get(i) != source:
                self.logo_sources[i] = source
                self.logo_images.pop(i, None)
                try:
                    image = tk.PhotoImage(master=self.root, data=source.split(',', 1)[1]) if source else None
                    if image:
                        image = image.subsample(max(1, math.ceil(max(image.width(), image.height()) / 64)))
                        self.logo_images[i] = image
                    self.logo_labels[i].configure(image=image or '', text='' if image else 'Sin escudo', width=0 if image else 12)
                except (tk.TclError, IndexError):
                    self.logo_labels[i].configure(image='', text='Escudo cargado', width=14)
            self.score_labels[i].configure(text=str(m['scores'][i]))
            self.win_labels[i].configure(text=f"Serie {c['teams'][i]['wins']}")
        state = snapshot['series']
        hint = f"BO{c['bestof']} · {state['target']} victorias para ganar"
        if c['bestof'] % 2 == 0:
            hint += f" · hasta {c['bestof']} partidos; admite empate"
        if state['complete']:
            hint += ' · EMPATE' if state['tied'] else ' · SERIE FINALIZADA'
        self.series_hint.configure(text=hint)
