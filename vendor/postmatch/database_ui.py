"""Database setup and asynchronous refresh; Tk is only touched on the UI thread."""
import copy
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .data_sources import PROVIDERS, PRE_CATALOG, auto_mapping, read_source, token, available_teams
from .stats_dialog import build_statistics


def build_database(app, parent):
    tabs = ttk.Notebook(parent)
    tabs.pack(fill='both', expand=True, padx=12, pady=(0, 12))
    connection_page = ttk.Frame(tabs)
    connection_canvas = tk.Canvas(connection_page, bg='#181426', highlightthickness=0)
    connection_scroll = ttk.Scrollbar(connection_page, orient='vertical', command=connection_canvas.yview)
    connection_scroll.pack(side='right', fill='y')
    connection_canvas.pack(fill='both', expand=True)
    connection_canvas.configure(yscrollcommand=connection_scroll.set)
    connection = ttk.Frame(connection_canvas, padding=12)
    connection_item = connection_canvas.create_window((0, 0), window=connection, anchor='nw')
    connection.bind('<Configure>', lambda e: connection_canvas.configure(scrollregion=connection_canvas.bbox('all')))
    connection_canvas.bind('<Configure>', lambda e: connection_canvas.itemconfigure(connection_item, width=e.width))
    def wheel(event):
        if connection.winfo_ismapped() and str(event.widget).startswith(str(connection_canvas)):
            connection_canvas.yview_scroll(-int(event.delta/120), 'units')
            return 'break'
    app.root.bind('<MouseWheel>', wheel, add='+')
    selection = ttk.Frame(tabs)
    tabs.add(connection_page, text='Conexión y datos')
    tabs.add(selection, text='Estadísticas de serie y torneo')
    app.prematch_notebook = tabs
    pre_sync = build_statistics(app, selection, prematch=True)
    variables = {key: tk.StringVar() for key in ('provider', 'location', 'credential_file', 'period', 'display', 'filter_column', 'filter_value', 'event', 'round')}
    widgets = {}
    def field(title, key, values=None):
        row = ttk.Frame(connection)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=title, width=22).pack(side='left')
        widget = (ttk.Combobox(row, textvariable=variables[key], values=values, state='readonly')
                  if values else ttk.Entry(row, textvariable=variables[key]))
        widget.pack(side='left', fill='x', expand=True)
        widgets[key] = widget
        return row
    field('Torneo', 'event')
    field('Ronda', 'round')
    field('Tipo de conexión', 'provider', list(PROVIDERS))
    row = field('Enlace / archivo / DSN', 'location')
    def browse():
        value = filedialog.askopenfilename(title='Base de datos SQLite', filetypes=[('SQLite', '*.db *.sqlite *.sqlite3'), ('Todos', '*.*')])
        if value:
            variables['location'].set(value)
    ttk.Button(row, text='Archivo…', command=browse).pack(side='left', padx=5)
    credentials_row = field('Credenciales Google', 'credential_file')
    def credentials():
        value = filedialog.askopenfilename(title='Credenciales de cuenta de servicio (opcional)', filetypes=[('JSON', '*.json')])
        if value:
            variables['credential_file'].set(value)
    ttk.Button(credentials_row, text='JSON…', command=credentials).pack(side='left', padx=5)
    ttk.Label(connection, text='Sheets: enlace público o JSON de cuenta de servicio para una hoja privada. SQLite: archivo. SQL / ODBC: nombre del DSN de Windows de 64 bits.\n'
              'Para servidores SQL, configura el DSN con una cuenta de solo lectura. Las contraseñas no se guardan en el perfil.',
              foreground='#a99ab5', wraplength=900).pack(anchor='w', pady=4)
    ttk.Label(connection, text='Consulta SQL (solo SELECT; para Sheets se ignora)').pack(anchor='w')
    query = tk.Text(connection, height=2, bg='#30283d', fg='white', insertbackground='white')
    query.pack(fill='x', pady=3)
    source_logos = tk.BooleanVar(value=True)
    ttk.Checkbutton(connection, text='Mostrar logos de la base de datos en Prepartido', variable=source_logos, command=app.apply, style='Marker.TCheckbutton').pack(anchor='w', pady=4)
    field('Mostrar datos', 'display', ['Automático', 'Solo equipos', 'Individuales'])
    field('Periodo de los datos', 'period', ['Serie', 'Torneo'])
    row = field('Filtrar por columna', 'filter_column', [''])
    ttk.Label(row, text=' Valor ').pack(side='left')
    ttk.Entry(row, textvariable=variables['filter_value'], width=20).pack(side='left')
    ttk.Label(connection, text='Si hay varias series o torneos en la fuente, filtra aquí o en tu consulta SQL. Una fila por equipo o jugador.',
              foreground='#a99ab5').pack(anchor='w', pady=3)
    bar = ttk.Frame(connection)
    bar.pack(fill='x', pady=5)
    info = ttk.Label(connection, foreground='#ffd14c', wraplength=900)
    info.pack(anchor='w', pady=3)
    team_vars = [tk.StringVar(), tk.StringVar()]
    team_boxes = []
    for side in range(2):
        row = ttk.Frame(connection)
        row.pack(fill='x', pady=2)
        ttk.Label(row, text=f'Equipo {side+1} de la fuente', width=22).pack(side='left')
        box = ttk.Combobox(row, textvariable=team_vars[side], state='readonly')
        box.pack(side='left', fill='x', expand=True)
        team_boxes.append(box)
        box.bind('<<ComboboxSelected>>', lambda event: select_teams())
    mapping = {}
    dataset = None
    results = queue.Queue()
    pending = False
    loaded_signature = None

    def settings():
        return dict(event=variables['event'].get(), round=variables['round'].get(), provider=variables['provider'].get(), location=variables['location'].get().strip(), credential_file=variables['credential_file'].get().strip(),
                    query=query.get('1.0', 'end-1c'), display=variables['display'].get(), period='series' if variables['period'].get() == 'Serie' else 'tournament',
                    filter_column=variables['filter_column'].get(), filter_value=variables['filter_value'].get(), mapping=dict(mapping), team_names=[v.get() for v in team_vars], show_logos=source_logos.get())

    def signature(c):
        return c['provider'], c['location'], c['query'] if c['provider'] != 'Google Sheets' else c.get('credential_file', '')

    def fill_teams():
        if dataset is None:
            return
        names = available_teams(dataset, mapping)
        for i, box in enumerate(team_boxes):
            box.configure(values=names)
            current = team_vars[i].get() or app.store.config['database']['team_names'][i]
            team_vars[i].set(next((name for name in names if token(name) == token(current)), names[i] if len(names) == 2 else ''))

    def connect():
        nonlocal pending, dataset, loaded_signature
        if pending:
            return
        config = settings()
        pending = True
        dataset, loaded_signature = None, None
        for box, var in zip(team_boxes, team_vars):
            box.configure(values=[])
            var.set('')
        info.configure(text='Conectando…')
        with app.store.lock:
            app.store.prematch_data = None
            app.store.prematch = None
        def worker():
            try:
                result = read_source(config)
                results.put((config, result, None))
            except Exception as exc:
                error = str(exc) if config['provider'] != 'SQL / ODBC' else 'No se pudo consultar el DSN. Comprueba el controlador, los permisos, la conexión y la consulta SELECT.'
                results.put((config, None, error))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        nonlocal pending, dataset, loaded_signature
        try:
            config, value, error = results.get_nowait()
        except queue.Empty:
            pass
        else:
            pending = False
            if signature(settings()) != signature(config):
                dataset, loaded_signature = None, None
                info.configure(text='La conexión ha cambiado. Pulsa Conectar / Actualizar para leer la nueva fuente.')
            elif error:
                dataset, loaded_signature = None, None
                info.configure(text=error)
            else:
                dataset, loaded_signature = value, signature(config)
                saved_mapping = dict(mapping) if loaded_signature == signature(config) else config.get('mapping', {})
                mapping.clear()
                mapping.update(auto_mapping(value['headers']))
                mapping.update({k: v for k, v in saved_mapping.items() if v in value['headers'] or (k == 'Name' and not v)})
                if mapping.get('Name') == mapping.get('Team'):
                    mapping['Name'] = ''
                widgets['filter_column'].configure(values=['']+value['headers'])
                fill_teams()
                with app.store.lock:
                    app.store.prematch_data = copy.deepcopy(value)
                    app.store.prematch_source = loaded_signature
                info.configure(text=f'{len(value["rows"])} filas leídas · '+('Datos individuales' if mapping.get('Name') else 'Datos de equipos'))
                select_teams()
                if app.apply():
                    with app.store.lock:
                        app.store.try_prematch()
        if app.active:
            app.root.after(200, poll)

    def assign():
        if dataset is None:
            messagebox.showinfo('Columnas', 'Conecta primero la fuente de datos.')
            return
        dialog = tk.Toplevel(app.root)
        dialog.title('Asignar columnas de la fuente')
        dialog.geometry('650x650')
        footer = ttk.Frame(dialog, padding=8)
        footer.pack(side='bottom', fill='x')
        canvas = tk.Canvas(dialog, bg='#181426', highlightthickness=0)
        scroll = ttk.Scrollbar(dialog, orient='vertical', command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas, padding=12)
        item = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        choices = {}
        for key, label in [('Team', 'Equipo (obligatorio)'), ('Name', 'Jugador (vacío = solo equipos)'), ('Logo', 'Logo del equipo (opcional)')]+[(m['key'], m['label']) for m in PRE_CATALOG]:
            row = ttk.Frame(content)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=33).pack(side='left')
            choices[key] = tk.StringVar(value=mapping.get(key, ''))
            ttk.Combobox(row, textvariable=choices[key], values=['']+dataset['headers'], state='readonly').pack(side='left', fill='x', expand=True)
        def save():
            mapping.update({k: v.get() for k, v in choices.items()})
            fill_teams()
            app.apply()
            dialog.destroy()
        ttk.Button(footer, text='Guardar asignación', command=save).pack(side='right')
        dialog.transient(app.root)

    def select_teams():
        if dataset is None or loaded_signature != signature(settings()):
            return
        names = [v.get() for v in team_vars]
        if not all(names):
            return
        if token(names[0]) == token(names[1]):
            info.configure(text='Selecciona dos equipos diferentes.')
            return
        if app.apply():
            with app.store.lock:
                app.store.prematch_error = ''
            info.configure(text='Datos de '+names[0]+' y '+names[1]+' cargados automáticamente desde la fuente.')

    ttk.Button(bar, text='Conectar / Actualizar', command=connect).pack(side='left')
    ttk.Button(bar, text='Asignar columnas…', command=assign).pack(side='left', padx=4)
    ttk.Label(connection, text='Al seleccionar los equipos, sus datos se cargan automáticamente desde la fuente.',
              foreground='#a99ab5').pack(anchor='w', pady=4)
    widgets['filter_column'].bind('<<ComboboxSelected>>', lambda event: select_teams())
    variables['filter_value'].trace_add('write', lambda *args: app.root.after_idle(select_teams))
    def sync(c):
        config = c['database']
        source_logos.set(config['show_logos'])
        for i, name in enumerate(config['team_names']):
            team_vars[i].set(name)
        for key, var in variables.items():
            var.set(('Serie' if config['period'] == 'series' else 'Torneo') if key == 'period' else config.get(key, ''))
        query.delete('1.0', 'end')
        query.insert('1.0', config['query'])
        mapping.clear()
        mapping.update(config['mapping'])
        pre_sync(c)
        if dataset is not None:
            fill_teams()
    app.database_settings = settings
    app.database_connect = connect
    app.root.after(200, poll)
    return sync
