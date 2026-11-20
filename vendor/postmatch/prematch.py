"""Series display state, independent from providers and match statistics."""
import copy
from .data_sources import presentation
from .source_logos import source_team_logos


def source_signature(c):
    return c['provider'], c['location'], c['query'] if c['provider'] != 'Google Sheets' else c.get('credential_file', '')


class PrematchState:
    def init_prematch(self):
        self.prematch = None
        self.prematch_data = None
        self.prematch_logos = {}
        self.prematch_source = None
        self.prematch_consumed = False
        self.playing = False
        self.prematch_error = ''
        self.prematch_ended_guid = None

    def hide_prematch(self):
        with self.lock:
            self.prematch = None

    def show_prematch(self, manual=False):
        with self.lock:
            c = self.config
            if not c['prematch_enabled']:
                raise ValueError('Activa Prepartido en el selector.')
            if self.prematch_data is None or self.prematch_source != source_signature(c['database']):
                raise ValueError('Conecta la fuente de datos antes de mostrar el prepartido.')
            if not manual and (self.prematch_consumed or self.playing or c['game'] != 1 or any(t['wins'] for t in c['teams'])):
                return False
            self.prematch = self.prematch_preview()
            self.prematch_consumed = True
            self.prematch_error = ''
            return True

    def prematch_preview(self):
        with self.lock:
            c = self.config
            if self.prematch_data is None or self.prematch_source != source_signature(c['database']):
                raise ValueError('Conecta la fuente de datos para ver la previa.')
            pre_config = copy.deepcopy(c)
            for key in ('event', 'round'):
                pre_config[key] = c['database'][key]
            names = c['database']['team_names']
            if not all(names) or names[0].casefold() == names[1].casefold():
                raise ValueError('Selecciona dos equipos diferentes en Conexión y datos.')
            for i, name in enumerate(names):
                pre_config['teams'][i]['name'] = name
            logos = source_team_logos(self.prematch_data, c['database'], pre_config['teams'], self.prematch_logos)
            for i, logo in enumerate(logos):
                pre_config['teams'][i]['logo'] = logo
            pre_config['show_logos'] = c['database']['show_logos']
            players, totals, individual = presentation(self.prematch_data, c['database'], pre_config['teams'], c['pre_metrics'])
            return dict(kind='prematch', visible=True, winner=None, config=pre_config,
                                 match=dict(players=players, scores=['—', '—']),
                                 statistics={'match': [players, totals]}, individual=individual,
                                 metrics=list(c['pre_metrics']), team_mode=c['pre_team_mode'],
                                 period=c['database']['period'])

    def prepare_series(self):
        with self.lock:
            self.prematch_consumed = False
            self.playing = False
            self.prematch = self.postmatch = None
            self.try_prematch()

    def try_prematch(self):
        if self.config['prematch_enabled']:
            try:
                self.show_prematch()
            except ValueError as exc:
                self.prematch_error = str(exc)

    def prematch_event(self, event, guid=None):
        if event == 'MatchEnded':
            self.prematch_ended_guid = guid or self.match_guid
        if event in ('MatchCreated', 'MatchInitialized', 'CountdownBegin'):
            self.try_prematch()
        elif event in ('RoundStarted', 'MatchStarted', 'MatchEnded'):
            self.prematch = None
            self.playing = True
            self.prematch_consumed = True


PRE_KEYS = ('prematch_enabled', 'pre_metrics', 'pre_team_mode', 'database')

def normalize_prematch(raw):
    from .data_sources import DB_DEFAULT, PRE_CATALOG, PRE_DEFAULT
    metrics = raw.get('pre_metrics', PRE_DEFAULT)
    keys = {metric['key'] for metric in PRE_CATALOG}
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 6 or any(not isinstance(key, str) or key not in keys for key in metrics) or len(set(metrics)) != len(metrics):
        raise ValueError('Elige entre 1 y 6 estadísticas diferentes para el prepartido.')
    database = raw.get('database', {})
    if not isinstance(database, dict):
        raise ValueError('La conexión de datos debe ser un objeto.')
    config = copy.deepcopy(DB_DEFAULT)
    for key in ('provider', 'location', 'credential_file', 'query', 'period', 'display', 'filter_column', 'filter_value'):
        config[key] = str(database.get(key, config[key]))[:10000]
    mapping = database.get('mapping', {})
    if not isinstance(mapping, dict):
        raise ValueError('La asignación de columnas no es válida.')
    config['mapping'] = {str(k): str(v)[:200] for k, v in mapping.items() if k in keys or k in ('Team', 'Name', 'GamesRecord', 'Logo')}
    names = database.get('team_names', ['', ''])
    if not isinstance(names, list) or len(names) != 2 or any(not isinstance(name, str) for name in names):
        raise ValueError('Selecciona dos equipos de la fuente.')
    config['team_names'] = [name.strip()[:80] for name in names]
    config['show_logos'] = bool(database.get('show_logos', True))
    for key in ('event', 'round'):
        config[key] = str(database.get(key, raw.get(key, '')))[:120]
    mode = raw.get('pre_team_mode', 'total')
    return dict(prematch_enabled=bool(raw.get('prematch_enabled', True)), pre_metrics=list(metrics),
                pre_team_mode=mode if mode in ('total', 'mean', 'difference', 'share') else 'total', database=config)
