"""Windows desktop application. Python 3.11+, standard library only."""
import copy
import json
import math
import os
import queue
import sys
import threading
import time
import uuid
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
from pathlib import Path
import webbrowser

from studio import Studio, GameConnection, defaults, validate, detect_decal, fingerprint, CARS
from server import make_server
from render import prepare, cached_clips
from library import Library
from obs import OBS, SCENES
from marker import MarkerPanel
from media import imported_manifest, mp4_duration

ROOT = Path(__file__).resolve().parent
DATA = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else ROOT)/'data'
LIBRARY = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'Piruleta Studio'/'Biblioteca'
LABELS = dict(pre='Prepartido', game='Partido', stats='Estadísticas',
              victory0='Victoria A', victory1='Victoria B', complete='Fin de serie')


class App:
    def __init__(self, root, library_dir=None):
        self.root = root
        self.library = Library(library_dir or LIBRARY)
        self.profile_fingerprints = set()
        root.title('Piruleta Studio · Control de retransmisión')
        root.geometry('1190x880')
        root.minsize(1000, 760)
        root.configure(bg='#14121e')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background='#201c2e', foreground='#faf6ff', font=('Segoe UI', 10))
        style.configure('TFrame', background='#14121e')
        style.configure('TLabelframe', background='#201c2e', padding=12)
        style.configure('TLabelframe.Label', foreground='#ffb4df', font=('Segoe UI', 11, 'bold'))
        style.configure('TEntry', fieldbackground='#100e18', foreground='#ffffff', padding=5)
        style.configure('TSpinbox', fieldbackground='#100e18', foreground='#ffffff', insertcolor='#ffffff', arrowsize=14)
        style.configure('TCombobox', fieldbackground='#100e18', foreground='#ffffff', padding=5)
        style.map('TCombobox', fieldbackground=[('readonly', '#100e18')], foreground=[('readonly', '#ffffff')])
        style.configure('TButton', background='#3b304b', padding=(12, 7))
        style.map('TButton', background=[('active', '#65415d')])
        style.configure('Accent.TButton', background='#e749a0', foreground='white', font=('Segoe UI', 10, 'bold'))
        style.configure('Title.TLabel', background='#14121e', font=('Segoe UI', 25, 'bold'))
        self.store = Studio()
        self.game = GameConnection(self.store)
        self.media = {}
        self.profile = None
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.render_thread = None
        self.stop = threading.Event()
        self.obs = OBS()
        self.obs_settings = None
        self.obs_version = 0
        self.obs_ready = False
        self.server = make_server(self.store, self.media)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.fields = []
        self.vars = {key: tk.StringVar(value=str(value)) for key, value in defaults().items() if key != 'teams'}
        self.vars['render_folder'] = tk.StringVar(value=str(DATA/'renders'))
        self.password = tk.StringVar()
        self.note = tk.StringVar(value='Completa los equipos para preparar la retransmisión.')
        self.status = tk.StringVar()
        self.obs_status = tk.StringVar(value='OBS · sin conectar')
        self.phase = tk.StringVar(value='Serie sin preparar')
        ttk.Label(root, text='PIRULETA STUDIO', style='Title.TLabel').pack(anchor='w', padx=24, pady=(18, 2))
        ttk.Label(root, text='Una serie. Un control. Toda la retransmisión.', background='#14121e', foreground='#b6a9c8').pack(anchor='w', padx=25, pady=(0, 14))
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill='both', expand=True, padx=20)
        self.setup_tab, self.setup, self.setup_canvas = self.scroll_page()
        self.control_tab = ttk.Frame(self.tabs)
        self.control = ttk.Frame(self.control_tab, padding=12)
        self.control.pack(fill='both', expand=True)
        self.category_pages = {}
        self.tabs.add(self.setup_tab, text='  1 · Datos de la serie  ')
        self.tabs.add(self.control_tab, text='  2 · Panel de control  ', state='disabled')
        def wheel(event):
            if event.widget.winfo_class() in ('TCombobox', 'TSpinbox', 'Text'):
                return
            canvas = self.category_pages.get(self.categories.select(), self.setup_canvas) if self.tabs.select() == str(self.control_tab) else self.setup_canvas
            canvas.yview_scroll(int(-event.delta/120), 'units')
        root.bind('<MouseWheel>', wheel)
        self.build_setup()
        self.build_control()
        self.populate(defaults())
        ttk.Label(root, textvariable=self.note, wraplength=1140, background='#14121e', foreground='#ffcf6a').pack(fill='x', padx=24, pady=(8, 2))
        ttk.Label(root, textvariable=self.status, background='#14121e', foreground='#b6a9c8').pack(fill='x', padx=24, pady=(0, 12))
        root.protocol('WM_DELETE_WINDOW', self.close)
        threading.Thread(target=self.obs_loop, daemon=True).start()
        root.after(100, self.tick)

    def scroll_page(self, parent=None):
        page = ttk.Frame(parent or self.tabs)
        canvas = tk.Canvas(page, background='#14121e', highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(canvas, padding=16)
        item = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        return page, inner, canvas

    def entry(self, parent, label, variable, row, browse=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=5)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky='ew', pady=5)
        if browse:
            ttk.Button(parent, text='Elegir…', command=browse).grid(row=row, column=2, padx=(6, 0))

    def build_setup(self):
        teams = ttk.Frame(self.setup)
        teams.pack(fill='x')
        for i in range(2):
            box = ttk.LabelFrame(teams, text=f'Equipo {i+1} · lado '+('azul' if i == 0 else 'naranja'))
            box.grid(row=0, column=i, sticky='nsew', padx=(0, 8) if i == 0 else (8, 0))
            teams.columnconfigure(i, weight=1)
            box.columnconfigure(1, weight=1)
            fields = {key: tk.StringVar() for key in ('name', 'short', 'logo', 'color', 'car', 'skin', 'skin_confirmed')}
            self.fields.append(fields)
            self.entry(box, 'Nombre *', fields['name'], 0)
            self.entry(box, 'Abreviatura *', fields['short'], 1)
            self.entry(box, 'Logo *', fields['logo'], 2, lambda i=i: self.pick_team(i, 'logo'))
            self.entry(box, 'Color *', fields['color'], 3, lambda i=i: self.pick_color(i))
            ttk.Label(box, text='Coche *').grid(row=4, column=0, sticky='w')
            ttk.Combobox(box, textvariable=fields['car'], values=CARS, state='readonly').grid(row=4, column=1, sticky='ew', pady=6)
            self.entry(box, 'Calcomanía', fields['skin'], 5, lambda i=i: self.pick_team(i, 'skin'))
            ttk.Button(box, text='Confirmar coche de la calcomanía', command=lambda i=i: self.confirm_skin(i)).grid(row=6, column=0, columnspan=3, sticky='w', pady=6)
        ttk.Label(self.setup, text='* Obligatorio. Calcomanías opcionales: solo Octane, Fennec y Dominus. ZIP o imagen; sin conversión entre coches.', wraplength=1080).pack(anchor='w', pady=12)
        series = ttk.LabelFrame(self.setup, text='Datos de la serie')
        series.pack(fill='x', pady=6)
        series.columnconfigure(1, weight=1)
        self.entry(series, 'Torneo / cabecera', self.vars['event'], 0)
        self.entry(series, 'Ronda', self.vars['round'], 1)
        ttk.Label(series, text='Duración de la serie *').grid(row=2, column=0, sticky='w')
        ttk.Combobox(series, textvariable=self.vars['bestof'], values=(1, 2, 3, 4, 5, 7), state='readonly', width=8).grid(row=2, column=1, sticky='w', pady=6)
        ttk.Label(series, text='BO2 y BO4 pueden acabar en empate.').grid(row=2, column=2)
        buttons = ttk.Frame(self.setup)
        buttons.pack(fill='x', pady=14)
        ttk.Button(buttons, text='Guardar datos…', command=self.save).pack(side='left')
        ttk.Button(buttons, text='Cargar datos…', command=self.load).pack(side='left', padx=8)
        self.continue_button = ttk.Button(buttons, text='Continuar al panel →', style='Accent.TButton', command=self.configure)
        self.continue_button.pack(side='right')

    def build_control(self):
        top = ttk.Frame(self.control)
        top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, textvariable=self.phase, font=('Segoe UI', 17, 'bold'), background='#14121e').pack(side='left')
        self.start_button = ttk.Button(top, text='Iniciar serie', command=self.start, state='disabled', style='Accent.TButton')
        self.start_button.pack(side='right')
        ttk.Button(top, text='Vista del programa', command=lambda: webbrowser.open(self.url+'/program')).pack(side='right', padx=8)
        connection = ttk.LabelFrame(self.control, text='Una única URL para OBS · fuente de navegador de 1920 × 1080')
        connection.pack(fill='x', pady=(0, 10))
        self.program_url = tk.StringVar(value=self.url+'/program')
        ttk.Entry(connection, textvariable=self.program_url, state='readonly').pack(side='left', fill='x', expand=True, padx=(0, 10))
        ttk.Button(connection, text='Copiar URL para OBS', command=self.copy_url).pack(side='right')
        self.categories = ttk.Notebook(self.control)
        self.categories.pack(fill='both', expand=True)
        pages = {}
        for key, title in (('marker', 'Marcador'), ('blender', 'Blender y animaciones'), ('stats', 'Estadísticas'), ('program', 'Emisión y OBS')):
            page, inner, canvas = self.scroll_page(self.categories)
            self.categories.add(page, text='  '+title+'  ')
            self.category_pages[str(page)] = canvas
            pages[key] = inner
        self.marker = MarkerPanel(pages['marker'], self)
        self.build_animation_controls(pages['blender'])
        self.build_stats_controls(pages['stats'])
        self.build_program_controls(pages['program'])

    def build_animation_controls(self, parent):
        prep = ttk.LabelFrame(parent, text='Generar animaciones con Blender')
        prep.pack(fill='x', pady=(0, 12))
        prep.columnconfigure(1, weight=1)
        self.entry(prep, 'Aplicación Blender', self.vars['blender'], 0, self.pick_blender)
        self.entry(prep, 'Guardar animaciones en', self.vars['render_folder'], 1, self.pick_render_folder)
        ttk.Label(prep, text='Modo de render').grid(row=2, column=0, sticky='w', pady=8)
        mode = ttk.Combobox(prep, textvariable=self.vars['render_engine'], values=('EEVEE', 'CYCLES'), state='readonly', width=14)
        mode.grid(row=2, column=1, sticky='w')
        mode.bind('<<ComboboxSelected>>', self.change_engine)
        ttk.Label(prep, text='EEVEE: rápido · CYCLES: calidad').grid(row=2, column=2, sticky='w')
        row = ttk.Frame(prep)
        row.grid(row=3, column=0, columnspan=3, sticky='ew', pady=10)
        self.render_button = ttk.Button(row, text='Preparar vídeos · generar solo los que faltan', command=self.render, style='Accent.TButton')
        self.render_button.pack(side='left')
        ttk.Button(row, text='Cancelar generación', command=self.cancelled.set).pack(side='left', padx=8)
        ttk.Button(row, text='Cargar preparación…', command=self.load_manifest).pack(side='left')
        ttk.Label(prep, text='EEVEE es el modo rápido predeterminado. Solo los vídeos nuevos necesitan Blender 4.4 o posterior. '
                  'Se recuperan automáticamente los que coinciden con los equipos y el modo de render.', wraplength=980).grid(row=4, column=0, columnspan=3, sticky='w')
        library = ttk.LabelFrame(parent, text='Biblioteca local de logos, calcomanías y vídeos')
        library.pack(fill='x', pady=(0, 12))
        ttk.Label(library, text=str(self.library.root), wraplength=980).pack(anchor='w')
        ttk.Label(library, text='Al continuar con los datos se guardan copias de tus recursos. La coincidencia se comprueba por contenido, '
                  'aunque el archivo tenga otro nombre o esté en otra carpeta.', wraplength=980).pack(anchor='w', pady=6)
        row = ttk.Frame(library)
        row.pack(fill='x')
        ttk.Button(row, text='Abrir biblioteca', command=self.open_library).pack(side='left')
        ttk.Button(row, text='Comprobar vídeos guardados', command=self.check_library).pack(side='left', padx=8)
        manual = ttk.LabelFrame(parent, text='Usar vídeos propios · no requiere Blender')
        manual.pack(fill='x', pady=(0, 12))
        manual.columnconfigure(1, weight=1)
        self.video_fields = {key: tk.StringVar() for key in ('pre', 'victory0', 'victory1')}
        for row, (key, title) in enumerate((('pre', 'Prepartido'), ('victory0', 'Victoria equipo A'), ('victory1', 'Victoria equipo B'))):
            self.entry(manual, title, self.video_fields[key], row, lambda k=key: self.pick_video(k))
        ttk.Label(manual, text='Selecciona tres MP4 con vídeo H.264. La duración de cada animación se detecta automáticamente. '
                  'Comprueba que cada victoria corresponde al equipo A/B de los datos iniciales.', wraplength=980).grid(row=3, column=0, columnspan=3, sticky='w', pady=10)
        ttk.Button(manual, text='Usar estos tres vídeos', command=self.use_manual_videos, style='Accent.TButton').grid(row=4, column=0, columnspan=3, sticky='w')
        self.video_summary = tk.StringVar(value='Sin vídeos preparados. Puedes generarlos o seleccionar los tuyos.')
        ttk.Label(parent, textvariable=self.video_summary, wraplength=980, foreground='#ffcf6a').pack(anchor='w', pady=8)
        view = ttk.LabelFrame(parent, text='Mostrar animaciones en la emisión')
        view.pack(fill='x', pady=8)
        for key in ('pre', 'victory0', 'victory1'):
            ttk.Button(view, text=LABELS[key], command=lambda k=key: self.force(k)).pack(side='left', padx=4)
        ttk.Button(view, text='Cortar animación', command=lambda: self.store.duration('cut')).pack(side='left', padx=10)

    def build_stats_controls(self, parent):
        box = ttk.LabelFrame(parent, text='Estadísticas de final de partido')
        box.pack(fill='x')
        self.stats_auto = tk.BooleanVar(value=True)
        self.stats_duration = tk.StringVar(value='10')
        ttk.Checkbutton(box, text='Mostrar automáticamente al terminar cada partido', variable=self.stats_auto,
                        command=self.apply_stats_options).pack(anchor='w', pady=8)
        row = ttk.Frame(box)
        row.pack(fill='x', pady=8)
        ttk.Label(row, text='Duración predeterminada (segundos)').pack(side='left')
        ttk.Spinbox(row, from_=1, to=300, textvariable=self.stats_duration, width=7).pack(side='left', padx=10)
        ttk.Button(row, text='Aplicar', command=self.apply_stats_options).pack(side='left')
        ttk.Label(box, text='Por defecto: 10 segundos después de cada partido. En el partido que decide la serie, '
                  'primero se reproduce la victoria completa y después aparecen las estadísticas.', wraplength=980).pack(anchor='w', pady=8)
        row = ttk.Frame(box)
        row.pack(fill='x', pady=10)
        ttk.Button(row, text='Mostrar hasta que las quite', command=lambda: self.show_statistics(False)).pack(side='left')
        ttk.Button(row, text='Mostrar con temporizador', command=lambda: self.show_statistics(True)).pack(side='left', padx=8)
        ttk.Button(row, text='Ocultar estadísticas', command=self.store.hide_stats, style='Accent.TButton').pack(side='left')
        row = ttk.Frame(box)
        row.pack(fill='x', pady=(0, 8))
        ttk.Button(row, text='Añadir 10 segundos', command=lambda: self.stats_timer('extend')).pack(side='left')
        ttk.Button(row, text='Pausar / reanudar temporizador', command=lambda: self.stats_timer('hold')).pack(side='left', padx=8)
        self.stats_summary = tk.StringVar(value='Esperando al primer partido finalizado.')
        ttk.Label(parent, textvariable=self.stats_summary, wraplength=980, foreground='#ffcf6a').pack(anchor='w', pady=18)

    def build_program_controls(self, parent):
        scenes = ttk.LabelFrame(parent, text='Control de la emisión')
        scenes.pack(fill='x', pady=(0, 12))
        for key in ('game', 'complete'):
            ttk.Button(scenes, text=LABELS[key], command=lambda k=key: self.force(k)).pack(side='left', padx=4)
        ttk.Button(scenes, text='Cortar escena actual', command=lambda: self.store.duration('cut')).pack(side='left', padx=8)
        ttk.Button(scenes, text='Añadir 10 s', command=lambda: self.store.duration('extend')).pack(side='left')
        ttk.Button(scenes, text='Pausar / reanudar temporizador', command=lambda: self.store.duration('hold')).pack(side='left', padx=8)
        obs = ttk.LabelFrame(parent, text='Opcional · cambiar también las escenas de OBS (WebSocket 5)')
        obs.pack(fill='x', pady=10)
        row = ttk.Frame(obs)
        row.pack(fill='x')
        ttk.Label(row, text='Puerto').pack(side='left')
        ttk.Entry(row, textvariable=self.vars['obs_port'], width=7).pack(side='left', padx=8)
        ttk.Label(row, text='Contraseña').pack(side='left')
        ttk.Entry(row, textvariable=self.password, show='•', width=20).pack(side='left', padx=8)
        ttk.Button(row, text='Conectar y preparar escenas', command=self.connect_obs).pack(side='left')
        ttk.Label(obs, textvariable=self.obs_status, wraplength=980).pack(anchor='w', pady=8)
        ttk.Label(parent, text='La URL única funciona sin WebSocket ni contraseña. Añádela encima de la captura del juego y mantén la app abierta. '
                  'Si usas el control opcional de escenas, coloca la captura debajo de «Piruleta · Programa» en «Piruleta · Partido».', wraplength=980).pack(anchor='w', pady=8)

    def pick_render_folder(self):
        path = filedialog.askdirectory(title='Dónde guardar las animaciones generadas')
        if path:
            self.vars['render_folder'].set(path)

    def open_library(self):
        try:
            self.library.root.mkdir(parents=True, exist_ok=True)
            os.startfile(self.library.root)
        except Exception as exc:
            self.error(exc)

    def change_engine(self, event=None):
        if not self.profile:
            return
        if self.store.armed or (self.render_thread and self.render_thread.is_alive()):
            self.vars['render_engine'].set(self.profile.get('render_engine', 'EEVEE'))
            self.error('Cambia el modo antes de iniciar la serie o de generar sus vídeos.')
            return
        self.profile['render_engine'] = self.vars['render_engine'].get()
        self.media.clear()
        self.start_button.configure(state='disabled')
        for variable in self.video_fields.values():
            variable.set('')
        self.check_library()

    def check_library(self):
        if not self.profile or self.store.armed or (self.render_thread and self.render_thread.is_alive()):
            return
        try:
            clips = cached_clips(self.profile, self.library.root)
            count = sum(clip is not None for clip in clips.values())
            if count == 3:
                self.accept_manifest(dict(fingerprint=fingerprint(self.profile), source='library',
                                          engine=self.profile.get('render_engine', 'EEVEE'),
                                          files={key: clip['path'] for key, clip in clips.items()}, reused=list(clips)))
                self.note.set('Los tres vídeos coinciden con la biblioteca y están listos. No hace falta renderizar.')
            else:
                self.video_summary.set(f'Biblioteca: {count}/3 vídeos disponibles para '+self.profile.get('render_engine', 'EEVEE')+
                                       '. Preparar vídeos generará únicamente los que faltan.')
        except Exception as exc:
            self.error(exc)

    def pick_video(self, key):
        path = filedialog.askopenfilename(title='Seleccionar '+LABELS[key], filetypes=[('Vídeo MP4 H.264', '*.mp4')])
        if path:
            try:
                duration = mp4_duration(path)
                self.video_fields[key].set(path)
                self.video_summary.set(LABELS[key]+f' seleccionado · {duration:.2f} s. Pulsa Usar estos tres vídeos para aplicarlos.')
            except Exception as exc:
                self.error(exc)

    def use_manual_videos(self):
        if self.store.armed or (self.render_thread and self.render_thread.is_alive()):
            self.error('Configura una nueva serie o espera a terminar la generación antes de cambiar los vídeos.')
            return
        try:
            manifest = imported_manifest(fingerprint(self.profile), {k: v.get() for k, v in self.video_fields.items()})
            self.accept_manifest(manifest)
        except Exception as exc:
            self.error(exc)

    def apply_stats_options(self):
        try:
            seconds = int(self.stats_duration.get())
            if not 1 <= seconds <= 300:
                raise ValueError('La duración debe estar entre 1 y 300 segundos.')
            with self.store.lock:
                self.store.stats_seconds = seconds
                self.store.stats_enabled = self.stats_auto.get()
            self.note.set(f'Estadísticas: {seconds} s. Aparición automática '+('activada.' if self.stats_auto.get() else 'desactivada.'))
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def show_statistics(self, timed):
        if self.apply_stats_options():
            try:
                self.store.show_stats(timed)
            except Exception as exc:
                self.error(exc)

    def stats_timer(self, action):
        if self.store.phase == 'stats':
            self.store.duration(action)

    def populate(self, profile):
        for key, var in self.vars.items():
            var.set(str(profile.get(key, defaults().get(key, var.get()))))
        for fields, team in zip(self.fields, profile['teams']):
            for key, var in fields.items():
                var.set(team.get(key, ''))

    def collect(self):
        profile = {key: var.get() for key, var in self.vars.items()}
        for key in ('bestof', 'obs_port', 'api_port'):
            profile[key] = int(profile[key])
        profile['teams'] = [{k: v.get() for k, v in fields.items()} for fields in self.fields]
        return profile

    def error(self, exc):
        messagebox.showerror('Piruleta Studio', str(exc), parent=self.root)

    def pick_team(self, i, field):
        types = [('Calcomanía', '*.zip *.png *.jpg *.jpeg *.tga *.dds')] if field == 'skin' else [('Logo', '*.png *.jpg *.jpeg')]
        path = filedialog.askopenfilename(filetypes=types)
        if path:
            self.fields[i][field].set(path)
            if field == 'skin':
                self.fields[i]['skin_confirmed'].set('')
                try:
                    model = detect_decal(path)
                    if model:
                        self.fields[i]['car'].set(model)
                        self.note.set('Calcomanía identificada: '+model+'. Coche actualizado.')
                    else:
                        self.note.set('Coche no identificable. Confirma la compatibilidad de esta calcomanía.')
                except Exception as exc:
                    self.error(exc)

    def confirm_skin(self, i):
        fields = self.fields[i]
        if fields['skin'].get():
            fields['skin_confirmed'].set(fields['car'].get())
            self.note.set('Compatibilidad confirmada por el usuario para '+fields['car'].get())

    def pick_color(self, i):
        color = colorchooser.askcolor(color=self.fields[i]['color'].get(), parent=self.root)[1]
        if color:
            self.fields[i]['color'].set(color)

    def pick_blender(self):
        path = filedialog.askopenfilename(filetypes=[('Blender', 'blender.exe')])
        if path:
            self.vars['blender'].set(path)

    def save(self):
        try:
            profile = self.collect()
            path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Datos de serie', '*.json')])
            if path:
                Path(path).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            self.error(exc)

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Datos de serie', '*.json')])
        if path:
            try:
                profile = json.loads(Path(path).read_text(encoding='utf-8-sig'))
                self.populate(validate(profile))
            except Exception as exc:
                self.error(exc)

    def configure(self):
        try:
            profile = validate(self.collect())
            if self.store.armed and not messagebox.askyesno('Nueva serie', 'Esto detendrá la automatización y reiniciará el resultado de la serie. ¿Continuar?', parent=self.root):
                return
            self.profile_fingerprints = {fingerprint(profile)}
            profile = self.library.import_profile(profile)
            self.profile_fingerprints.add(fingerprint(profile))
            self.populate(profile)
            self.profile = profile
            self.store.configure(profile)
            self.media.clear()
            self.start_button.configure(state='disabled')
            self.game.connect(profile['api_port'])
            self.tabs.tab(self.control_tab, state='normal')
            self.tabs.select(self.control_tab)
            self.marker.sync()
            for variable in self.video_fields.values():
                variable.set('')
            self.video_summary.set('Sin vídeos preparados para esta serie.')
            self.note.set('Datos sincronizados. Prepara los tres vídeos antes de iniciar la serie.')
            self.check_library()
        except Exception as exc:
            self.error(exc)

    def render(self):
        if self.store.armed:
            self.error('Configura una nueva serie antes de volver a preparar sus escenas.')
            return
        if self.render_thread and self.render_thread.is_alive():
            return
        self.cancelled.clear()
        profile = copy.deepcopy(self.profile)
        profile['blender'] = self.vars['blender'].get()
        profile['render_engine'] = self.vars['render_engine'].get()
        self.profile['render_engine'] = profile['render_engine']
        destination = self.vars['render_folder'].get().strip()
        if not destination:
            self.error('Selecciona dónde guardar las animaciones.')
            return
        self.render_button.configure(state='disabled')
        self.continue_button.configure(state='disabled')
        self.start_button.configure(state='disabled')
        self.note.set('Comprobando biblioteca. Se generarán solo los vídeos que falten · '+profile['render_engine'])
        def work():
            try:
                manifest = prepare(profile, destination, lambda msg: self.events.put(('note', msg)), self.cancelled,
                                   library_dir=self.library.root)
                self.events.put(('manifest', manifest))
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('render_done', None))
        self.render_thread = threading.Thread(target=work, daemon=True)
        self.render_thread.start()

    def accept_manifest(self, manifest):
        if manifest['fingerprint'] not in self.profile_fingerprints | {fingerprint(self.profile)}:
            raise ValueError('La preparación corresponde a otros datos. Vuelve a generar los vídeos.')
        if set(manifest['files']) != {'pre', 'victory0', 'victory1'}:
            raise ValueError('La preparación está incompleta. Se necesitan los tres vídeos.')
        durations = {key: mp4_duration(path) for key, path in manifest['files'].items()}
        updated = copy.deepcopy(manifest)
        updated.update(durations=durations, version=uuid.uuid4().hex)
        self.media.clear()
        self.media.update(updated)
        with self.store.lock:
            self.store.scene_seconds = durations
        for key, path in updated['files'].items():
            self.video_fields[key].set(path)
        origin = 'Vídeos propios' if updated.get('source') == 'manual' else ('Biblioteca' if updated.get('source') == 'library' else 'Preparación de Blender')
        if updated.get('engine'):
            origin += ' · '+updated['engine']
        self.video_summary.set(origin+' lista · '+ ' / '.join(LABELS[k]+f': {v:.2f} s' for k,v in durations.items()))
        self.start_button.configure(state='normal')
        self.note.set('Los tres vídeos están listos. Ya puedes iniciar la serie.')

    def load_manifest(self):
        if self.store.armed or (self.render_thread and self.render_thread.is_alive()):
            self.error('Espera a terminar la preparación o configura una nueva serie.')
            return
        path = filedialog.askopenfilename(title='Selecciona manifest.json de una preparación anterior', filetypes=[('Preparación', '*.json')])
        if path:
            try:
                self.accept_manifest(json.loads(Path(path).read_text(encoding='utf-8')))
            except Exception as exc:
                self.error(exc)

    def start(self):
        if not self.media:
            return
        if self.store.armed:
            self.error('La serie ya está iniciada. Para una nueva serie vuelve a Datos y pulsa Continuar.')
            return
        self.store.start()
        self.start_button.configure(state='disabled')
        self.note.set('Serie iniciada. Las escenas seguirán los finales de partido del juego.')

    def force(self, phase):
        if phase in ('pre', 'victory0', 'victory1') and not self.media:
            self.error('Prepara los vídeos antes de mostrar esta escena.')
            return
        if phase == 'stats' and not self.store.postmatch:
            self.error('Todavía no hay estadísticas de un partido finalizado.')
            return
        seconds = self.store.scene_seconds.get(phase, self.store.stats_seconds if phase == 'stats' else None)
        self.store.transition(phase, seconds)

    def copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url+'/program')
        self.note.set('URL copiada. Pégala en una fuente de navegador de OBS de 1920 × 1080. No necesitas conectar WebSocket.')

    def connect_obs(self):
        try:
            port = int(self.vars['obs_port'].get())
            if not 1 <= port <= 65535:
                raise ValueError('Puerto OBS inválido.')
            self.obs_settings = (port, self.password.get())
            self.obs_version += 1
            self.obs_status.set('OBS · conectando…')
        except Exception as exc:
            self.error(exc)

    def obs_loop(self):
        version, revision = -1, -1
        while not self.stop.wait(.05):
            if self.obs_settings is None:
                continue
            try:
                if version != self.obs_version or not self.obs.sock:
                    port, password = self.obs_settings
                    self.obs.connect(port, password)
                    self.obs.prepare(self.url)
                    version, revision = self.obs_version, -1
                    self.events.put(('obs', 'OBS · conectado'))
                with self.store.lock:
                    current, phase = self.store.revision, self.store.phase
                if current != revision:
                    # Do not change the live OBS scene just by connecting during setup.
                    if self.store.armed:
                        self.obs.switch(phase)
                    revision = current
                if not hasattr(self, '_ping') or time.monotonic()-self._ping > 5:
                    self.obs.request('GetVersion')
                    self._ping = time.monotonic()
            except Exception as exc:
                self.obs.close()
                self.events.put(('obs', 'OBS · reintentando: '+str(exc)))
                self.stop.wait(2)

    def tick(self):
        self.store.tick()
        state = self.store.snapshot()
        self.marker.refresh()
        result = state['postmatch']
        self.stats_summary.set(('Último partido: '+result['config']['teams'][0]['name']+' '+str(result['match']['scores'][0])+' — '+str(result['match']['scores'][1])+' '+result['config']['teams'][1]['name']) if result else 'Esperando al primer partido finalizado.')
        s = state['studio']
        suffix = f' · {math.ceil(s["remaining"])} s' if s['remaining'] is not None else ' · temporizador pausado' if s['held'] else ''
        self.phase.set(('Serie preparada · pendiente de inicio' if not self.store.armed and self.profile else LABELS[s['phase']])+suffix)
        self.status.set(state['connection']['status']+'   |   '+self.url+'/program'+('   |   Corrección manual activa' if s['manual'] else ''))
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'note':
                self.note.set(value)
            elif kind == 'obs':
                self.obs_status.set(value)
            elif kind == 'manifest':
                try:
                    self.accept_manifest(value)
                except Exception as exc:
                    self.error(exc)
            elif kind == 'error':
                self.error(value)
                self.note.set(value)
            elif kind == 'render_done':
                self.render_button.configure(state='normal')
                self.continue_button.configure(state='normal')
                if self.media and not self.store.armed:
                    self.start_button.configure(state='normal')
        self.root.after(100, self.tick)

    def close(self):
        self.stop.set()
        self.cancelled.set()
        if self.render_thread and self.render_thread.is_alive():
            self.render_thread.join(timeout=6)
        self.game.disconnect()
        self.server.shutdown()
        self.server.server_close()
        self.obs.close()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
