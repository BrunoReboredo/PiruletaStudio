"""Read-only providers returning the same table model for Sheets and SQL."""
import csv
import io
import math
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
from urllib.request import urlopen
from .metrics import CATALOG

EXTRA = [dict(key=k, label=l, group='Serie y torneo', unit='', aggregate='sum') for k, l in [
    ('LeaguePoints', 'Puntos de clasificación'), ('SeriesPlayed', 'Series jugadas'),
    ('SeriesWins', 'Series ganadas'), ('SeriesLosses', 'Series perdidas'),
    ('GoalsFor', 'Goles a favor'), ('GoalsAgainst', 'Goles en contra')]]
PRE_CATALOG = CATALOG + EXTRA
PRE_DEFAULT = ['Ranking', 'LeaguePoints', 'SeriesPlayed', 'SeriesWins', 'GoalsFor', 'GoalDiff']
DB_DEFAULT = dict(provider='Google Sheets', location='', credential_file='', query='SELECT * FROM estadisticas',
                  team_names=['', ''], show_logos=True, period='tournament', display='Automático', filter_column='', filter_value='', mapping={})

def token(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().lower())

ALIASES = {'Team': ['equipo', 'team', 'teamname'], 'Name': ['jugador', 'player', 'name', 'nombre'],
    'Logo': ['logo', 'escudo', 'logoequipo', 'teamlogo', 'logourl'],
    'Ranking': ['pos', 'posicion', 'ranking'], 'LeaguePoints': ['pts', 'puntosclasificacion'],
    'SeriesPlayed': ['sj', 'seriesjugadas'], 'SeriesWins': ['sg', 'seriesganadas'],
    'GoalsFor': ['gf'], 'GoalsAgainst': ['gc'], 'GoalDiff': ['dg', 'diferenciagfgc'], 'GamesRecord': ['gamesdif'], 'Goals': ['golesmarcados'], 'Assists': ['asistenciasdadas'], 'SeriesLosses': ['diferenciasjsg']}
for metric in PRE_CATALOG:
    ALIASES.setdefault(metric['key'], []).extend([token(metric['key']), token(metric['label'])])

def numeric(value):
    if value is None or str(value).strip() in ('', '-', '—'):
        return None
    text = str(value).strip().replace('%', '').replace('º', '').replace('ª', '').replace('\u00a0', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except ValueError:
        return None

def table(rows):
    """Locate the header, including league sheets with blank leading rows."""
    header = next((i for i, row in enumerate(rows[:100]) if any(token(cell) in ALIASES['Team'] for cell in row)), None)
    if header is None:
        header = next((i for i, row in enumerate(rows[:100]) if any(str(v).strip() for v in row)), None)
    for index, row in enumerate(rows[:100]):
        if index == header:
            headers = [str(cell).strip() or f'Columna {i+1}' for i, cell in enumerate(row)]
            if len(set(headers)) != len(headers):
                raise ValueError('Hay columnas con el mismo nombre. Usa encabezados únicos.')
            values = []
            for cells in rows[index+1:]:
                if not any(str(v).strip() for v in cells):
                    if values:
                        break  # end of the classification, not the fixtures below
                    continue
                values.append(dict(zip(headers, list(cells)+['']*len(headers))))
            return dict(headers=headers, rows=values)
    raise ValueError('No se encuentra una cabecera en las primeras 100 filas.')

def read_sheets(config):
    link = urlsplit(config['location'].strip())
    match = re.fullmatch(r'/spreadsheets/d/([\w-]+)(?:/.*)?', link.path)
    if link.scheme != 'https' or link.hostname != 'docs.google.com' or not match:
        raise ValueError('Introduce el enlace HTTPS de una hoja de Google Sheets.')
    gid = parse_qs(link.query).get('gid', parse_qs(link.fragment).get('gid', ['0']))[0]
    if not gid.isdigit():
        raise ValueError('El identificador de pestaña gid debe ser numérico.')
    return table(read_sheet_rows(config, match[1], gid))


def read_sheet_rows(config, spreadsheet_id, gid):
    if config.get('credential_file', '').strip():
        return read_private_sheet(spreadsheet_id, int(gid), config['credential_file'], raw=True)
    url = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}'
    try:
        with urlopen(url, timeout=20) as response:
            data = response.read(5_000_001)
            if len(data) > 5_000_000:
                raise ValueError('La pestaña supera el límite de 5 MB.')
            if 'text/html' in response.headers.get('Content-Type', ''):
                raise ValueError('La hoja pide iniciar sesión. Comparte la hoja con acceso de lectura por enlace.')
    except OSError as exc:
        raise ValueError(f'No se pudo leer la pestaña {gid}. Comprueba la conexión y los permisos de lectura.') from exc
    return list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))

def read_private_sheet(sheet_id, gid, credential_file, raw=False):
    """Optional service-account JSON; never copied into a profile or overlay state."""
    try:
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import AuthorizedSession
        credentials = Credentials.from_service_account_file(credential_file,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
        with AuthorizedSession(credentials) as session:
            base = f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}'
            meta = session.get(base, params={'fields': 'sheets.properties'}, timeout=20)
            meta.raise_for_status()
            title = next((s['properties']['title'] for s in meta.json()['sheets'] if s['properties']['sheetId'] == gid), None)
            if title is None:
                raise ValueError('No existe la pestaña gid indicada en el enlace.')
            area = "'"+title.replace("'", "''")+"'!A1:ZZ10001"
            result = session.get(base+'/values/'+quote(area, safe=''), params={'valueRenderOption': 'UNFORMATTED_VALUE'}, timeout=20)
            result.raise_for_status()
            rows = result.json().get('values', [])
            return rows if raw else table(rows)
    except Exception as exc:
        raise ValueError('No se pudo leer la hoja privada. Comprueba el archivo JSON, activa Sheets API y comparte la hoja con el correo de la cuenta de servicio.') from exc

def read_sql(config):
    query = config['query'].strip().rstrip(';').strip()
    if not re.match(r'^SELECT\b', query, re.I) or ';' in query:
        raise ValueError('Escribe una única consulta SELECT. Para servidores usa una cuenta de solo lectura.')
    if config['provider'] == 'SQLite':
        path = Path(config['location']).expanduser().resolve(strict=True)
        connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=10)
        connection.execute('PRAGMA query_only=ON')
        deadline = time.monotonic()+15
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    else:
        try:
            import pyodbc
        except ImportError as exc:
            raise ValueError('Esta instalación no incluye el conector ODBC.') from exc
        # DSN belongs to Windows, including authentication; no password in profiles.
        dsn = config['location'].strip()
        if not dsn or any(c in dsn for c in ';{}'):
            raise ValueError('Introduce el nombre de un DSN ODBC configurado en Windows (64 bits).')
        connection = pyodbc.connect(f'DSN={dsn}', timeout=15, readonly=True)
        connection.timeout = 15
    with closing(connection):
        cursor = connection.cursor()
        cursor.execute(query)
        headers = [column[0] for column in cursor.description]
        values = cursor.fetchmany(10001)
        if len(values) > 10000:
            raise ValueError('La consulta supera las 10.000 filas. Añade un filtro.')
        return table([headers]+[list(row) for row in values])

PROVIDERS = {'Google Sheets': read_sheets, 'SQLite': read_sql, 'SQL / ODBC': read_sql}

def read_source(config):
    if config.get('provider') not in PROVIDERS:
        raise ValueError('Selecciona un tipo de conexión.')
    return PROVIDERS[config['provider']](config)

def available_teams(dataset, mapping):
    names = {}
    for row in dataset['rows']:
        name = str(row.get(mapping.get('Team')) or '').strip()
        if name:
            names.setdefault(token(name), name)
    return sorted(names.values(), key=str.casefold)

def auto_mapping(headers):
    mapping = {key: next((h for h in headers if token(h) in aliases), '') for key, aliases in ALIASES.items()}
    normalized = {token(h): h for h in headers}
    if not mapping['Team'] and 'nombre' in normalized and 'seriesjugadas' in normalized and 'posicion' in normalized:
        mapping['Team'], mapping['Name'] = normalized['nombre'], ''
        if 'puntos' in normalized:
            mapping['LeaguePoints'] = normalized['puntos']
            if mapping.get('Score') == normalized['puntos']:
                mapping['Score'] = ''
    return mapping

def presentation(dataset, config, teams, selected):
    mapping = auto_mapping(dataset['headers'])
    mapping.update(config.get('mapping', {}))
    if mapping.get('Name') == mapping.get('Team'):
        mapping['Name'] = ''
    team_column, name_column = mapping.get('Team'), mapping.get('Name')
    if not team_column:
        raise ValueError('Asigna la columna Equipo.')
    if config.get('display') == 'Individuales' and not name_column:
        raise ValueError('La fuente solo contiene equipos. Selecciona Automático o Solo equipos.')
    rows = dataset['rows']
    column, value = config.get('filter_column'), config.get('filter_value', '').strip()
    if column:
        if column not in dataset['headers']:
            raise ValueError('La columna del filtro ya no existe.')
        rows = [row for row in rows if token(row.get(column, '')) == token(value)]
    players, totals = [], []
    for side, team in enumerate(teams):
        found = [row for row in rows if token(row.get(team_column, '')) == token(team['name'])]
        if not found:
            raise ValueError(f'No hay datos para {team["name"]}. Elige el equipo de la base de datos.')
        if len(found) > (3 if name_column else 1):
            raise ValueError(f'Hay varias filas por equipo/jugador para {team["name"]}. Filtra la serie o agrega los datos en la consulta.')
        members = []
        for i, row in enumerate(found):
            p = dict(Name=str(row.get(name_column) or team['name']), TeamNum=side, Shortcut=i)
            for metric in PRE_CATALOG:
                raw = row.get(mapping.get(metric['key']))
                p[metric['key']] = str(raw) if raw is not None and metric['unit'] == 'texto' else numeric(raw)
            record = re.match(r'\s*(\d+)\s*-\s*(\d+)', str(row.get(mapping.get('GamesRecord'), '')))
            if record:
                p.update(Wins=int(record[1]), Losses=int(record[2]), Matches=int(record[1])+int(record[2]))
            if p.get('SeriesPlayed') is not None and p.get('SeriesWins') is not None and p.get('SeriesLosses') is None:
                p['SeriesLosses'] = p['SeriesPlayed']-p['SeriesWins']
            if p.get('WinRate') is None and p.get('Matches') and p.get('Wins') is not None:
                p['WinRate'] = 100*p['Wins']/p['Matches']
            members.append(p)
        if name_column and len({p['Name'] for p in members}) != len(members):
            raise ValueError('La consulta devuelve varias filas del mismo jugador. Agrega o filtra los datos.')
        total = {}
        for metric in PRE_CATALOG:
            key = metric['key']
            values = [p[key] for p in members if isinstance(p.get(key), (float, int))]
            if len(values) != len(members):
                total[key] = None
            elif metric['aggregate'] == 'max':
                total[key] = max(values)
            elif metric['aggregate'] in ('sum',):
                total[key] = sum(values)
            elif len(values) == 1:
                total[key] = values[0]
            else:
                total[key] = None  # no misleading sums/averages for rates or rankings
        totals.append(total)
        if config.get('display') == 'Solo equipos':
            players.append(dict(total, Name=team['name'], TeamNum=side, Shortcut=0))
        else:
            players.extend(members)
    if not any(p.get(key) is not None for p in players for key in selected):
        raise ValueError('Ninguna estadística seleccionada tiene datos. Revisa la asignación de columnas.')
    return players, totals, bool(name_column) and config.get('display') != 'Solo equipos'
