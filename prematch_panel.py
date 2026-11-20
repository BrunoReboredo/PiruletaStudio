"""Source setup for the automatic, single opening statistics scene."""
import copy
import json
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from library import atomic_json
from vendor.postmatch.database_ui import build_database
from vendor.postmatch.prematch import PRE_KEYS, source_signature
from vendor.overlay.app import normalize_config


class PrematchPanel:
    def __init__(self, parent, owner, settings_file):
        self.owner = owner
        self.root = owner.root
        self.store = owner.store
        self.path = Path(settings_file)
        self.active = True
        ttk.Label(parent, text='Se muestra al preparar los vídeos y permanece hasta iniciar la serie y elegir Campo o Coches.',
                  wraplength=980).pack(anchor='w', pady=12)
        buttons = ttk.Frame(parent)
        buttons.pack(fill='x', pady=(0, 8))
        ttk.Button(buttons, text='Aplicar conexión y datos', command=self.apply).pack(side='left')
        ttk.Button(buttons, text='Guardar configuración…', command=self.save).pack(side='left', padx=8)
        ttk.Button(buttons, text='Cargar configuración…', command=self.load).pack(side='left')
        ttk.Button(buttons, text='Vista previa', command=self.preview).pack(side='left', padx=8)
        self.database_sync = build_database(self, parent)
        self.sync()
        if self.path.is_file():
            try:
                self.restore(json.loads(self.path.read_text(encoding='utf-8')))
            except (OSError, ValueError, TypeError) as exc:
                owner.note.set('No se pudo cargar la conexión de prepartido: '+str(exc))

    def sync(self, reconnect=False):
        self.database_sync(self.store.config)
        self.store.try_prematch()
        if reconnect and self.store.config['database']['location'] and self.store.prematch_source != source_signature(self.store.config['database']):
            self.database_connect()

    def apply(self):
        try:
            with self.store.lock:
                raw = copy.deepcopy(self.store.config)
                raw.update(self.pre_statistics_settings(), database=self.database_settings())
                updated = normalize_config(raw)
                self.store.config = updated
                self.store.try_prematch()
            atomic_json(self.path, {key: updated[key] for key in PRE_KEYS})
            return True
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror('Prepartido', str(exc), parent=self.root)
            return False

    def restore(self, values):
        with self.store.lock:
            raw = copy.deepcopy(self.store.config)
            raw.update({key: values[key] for key in PRE_KEYS if key in values})
            self.store.config = normalize_config(raw)
        self.sync()
        if self.store.config['database']['location']:
            self.database_connect()

    def preview(self):
        if not self.apply():
            return
        try:
            self.store.prematch_preview()
        except ValueError as exc:
            self.owner.error(exc)
            return
        import webbrowser
        webbrowser.open(self.owner.url+'/postmatch?preview=1&prematch=1')

    def save(self):
        if not self.apply():
            return
        filename = filedialog.asksaveasfilename(parent=self.root, defaultextension='.json',
                                              filetypes=[('Configuración de prepartido', '*.json')])
        if filename:
            try:
                atomic_json(Path(filename), {key: self.store.config[key] for key in PRE_KEYS})
            except OSError as exc:
                self.owner.error(exc)

    def load(self):
        filename = filedialog.askopenfilename(parent=self.root, filetypes=[('Configuración de prepartido', '*.json')])
        if filename:
            try:
                self.restore(json.loads(Path(filename).read_text(encoding='utf-8-sig')))
            except (OSError, ValueError, TypeError) as exc:
                self.owner.error(exc)
