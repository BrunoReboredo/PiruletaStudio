"""User-facing statistic picker: ordered selection of one to six rows."""
import tkinter as tk
from tkinter import ttk, messagebox
from .metrics import CATALOG, DEFAULT_METRICS


def build_statistics(app, parent, prematch=False):
    from .data_sources import PRE_CATALOG, PRE_DEFAULT
    catalog = PRE_CATALOG if prematch else [m for m in CATALOG if m['group'] != 'Serie y torneo']
    defaults_list = PRE_DEFAULT if prematch else DEFAULT_METRICS
    metrics_key = 'pre_metrics' if prematch else 'metrics'
    mode_key = 'pre_team_mode' if prematch else 'team_mode'
    win = parent
    outer = ttk.Frame(parent, padding=14)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='ELIGE HASTA 6 ESTADÍSTICAS', foreground='#fa54b7',
              font=('Segoe UI', 17, 'bold')).pack(anchor='w')
    ttk.Label(outer, text='Con menos de seis, las filas se centran. Cada fila conserva sus valores y barras.').pack(anchor='w', pady=8)
    settings = ttk.Frame(outer)
    settings.pack(fill='x', pady=10)
    mode_labels = {'Totales': 'total', 'Medias por jugador': 'mean', 'Diferencia entre equipos': 'difference', 'Porcentaje por equipo': 'share'}
    c = app.store.snapshot()['config']
    mode = tk.StringVar(value=next(k for k, v in mode_labels.items() if v == c[mode_key]))
    ttk.Label(settings, text='Comparativa central').pack(side='left', padx=(20, 8))
    ttk.Combobox(settings, textvariable=mode, values=list(mode_labels), state='readonly', width=26).pack(side='left')
    body = ttk.Frame(outer)
    body.pack(fill='both', expand=True)
    left = ttk.Frame(body)
    left.pack(side='left', fill='both', expand=True)
    canvas = tk.Canvas(left, bg='#181426', highlightthickness=0)
    scrollbar = ttk.Scrollbar(left, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    content = ttk.Frame(canvas)
    container = canvas.create_window((0, 0), window=content, anchor='nw')
    content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(container, width=event.width))
    def wheel(event):
        if parent.winfo_ismapped() and str(event.widget).startswith(str(left)):
            canvas.yview_scroll(-int(event.delta/120), 'units')
            return 'break'
    app.root.bind('<MouseWheel>', wheel, add='+')
    right = ttk.Frame(body, padding=(18, 0, 0, 0))
    right.pack(side='right', fill='y')
    ttk.Label(right, text='ORDEN EN PANTALLA', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=6)
    chosen = list(c[metrics_key])
    labels = {m['key']: m['label'] for m in catalog}
    selection = tk.Listbox(right, width=33, height=6, bg='#30283d', fg='white',
                          selectbackground='#91436c', exportselection=False)
    selection.pack(fill='x')
    count = ttk.Label(right, foreground='#ffd14c')
    count.pack(anchor='w', pady=8)
    variables, checks = {}, {}

    def refresh():
        current = selection.curselection()
        selection.delete(0, 'end')
        for i, key in enumerate(chosen):
            selection.insert('end', f'{i+1}. {labels[key]}')
        if current and current[0] < len(chosen):
            selection.selection_set(current[0])
        count.configure(text=f'{len(chosen)} / 6 seleccionadas')
        for key, var in variables.items():
            var.set(key in chosen)
            checks[key].configure(state='normal' if key in chosen or len(chosen) < 6 else 'disabled')

    def toggle(key):
        if variables[key].get():
            if key not in chosen and len(chosen) < 6:
                chosen.append(key)
        elif key in chosen:
            chosen.remove(key)
        refresh()

    previous_group = None
    for metric in catalog:
        key = metric['key']
        if metric['group'] != previous_group:
            previous_group = metric['group']
            ttk.Label(content, text=previous_group.upper(), foreground='#ff8875',
                      font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(14, 5))
        variables[key] = tk.BooleanVar(value=key in chosen)
        unit = f" ({metric['unit']})" if metric['unit'] and metric['unit'] != 'texto' else ''
        checks[key] = ttk.Checkbutton(content, text=metric['label']+unit, variable=variables[key],
                                     command=lambda key=key: toggle(key), style='Marker.TCheckbutton')
        checks[key].pack(anchor='w', pady=2)

    def move(delta):
        indexes = selection.curselection()
        if indexes and 0 <= indexes[0]+delta < len(chosen):
            i, j = indexes[0], indexes[0]+delta
            chosen[i], chosen[j] = chosen[j], chosen[i]
            refresh()
            selection.selection_clear(0, 'end')
            selection.selection_set(j)

    buttons = ttk.Frame(right)
    buttons.pack(fill='x', pady=6)
    ttk.Button(buttons, text='Subir', command=lambda: move(-1)).pack(side='left')
    ttk.Button(buttons, text='Bajar', command=lambda: move(1)).pack(side='left', padx=5)

    def defaults():
        chosen[:] = defaults_list
        refresh()

    ttk.Button(right, text='Restaurar selección inicial', command=defaults).pack(fill='x', pady=8)
    ttk.Label(right, text=('— = Sin datos en la fuente.\nLos periodos se filtran en Conexión.' if prematch else '— = Sin datos registrados.\nMVP = más puntos del partido.'),
              wraplength=260).pack(anchor='w', pady=8)

    def settings():
        if not chosen:
            raise ValueError('Elige al menos una estadística.')
        return {metrics_key: list(chosen), mode_key: mode_labels[mode.get()], **({} if prematch else {'stats_scope': 'match'})}

    def accept():
        try:
            selection_config = settings()
        except ValueError as exc:
            messagebox.showwarning('Selecciona estadísticas', str(exc), parent=win)
            return
        with app.store.lock:
            app.store.config.update(selection_config)
            if prematch and app.store.prematch:
                try:
                    app.store.prematch = app.store.prematch_preview()
                except ValueError as exc:
                    app.store.prematch = None
                    app.store.prematch_error = str(exc)
        if prematch:
            app.apply()
        count.configure(text=f'{len(chosen)} / 6 · Selección aplicada')

    footer = ttk.Frame(outer)
    footer.pack(side='bottom', fill='x', pady=(12, 0), before=body)
    ttk.Button(footer, text='Mostrar selección', command=accept).pack(side='right')
    refresh()
    def sync(config):
        chosen[:] = config[metrics_key]
        mode.set(next(k for k, v in mode_labels.items() if v == config[mode_key]))
        refresh()

    if prematch:
        app.pre_statistics_settings = settings
    else:
        app.accept_statistics = accept
        app.statistics_settings = settings
    return sync
