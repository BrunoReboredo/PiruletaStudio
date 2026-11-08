"""Editable stadium footage projects, independent of the car templates."""
import copy
import json
import math
import re
import uuid
from pathlib import Path
from .media import mp4_duration
from .stadium_layout import apply_team_layout

STADIUMS = ('Champions Field', 'Mannfield', 'Estadio DFH')
STADIUM_FILES = dict(zip(STADIUMS, ('Champions_Field', 'Mannfield', 'Estadio_DFH')))


def stadium_project(runtime, stadium):
    """Load the bundled neutral layout and its immutable stadium footage."""
    if stadium not in STADIUM_FILES:
        raise ValueError('Elige uno de los tres estadios disponibles.')
    folder = Path(runtime)/'assets'/'stadiums'
    project = load(folder/(STADIUM_FILES[stadium]+'.json'))
    project['video'] = str(folder/(STADIUM_FILES[stadium]+'.mp4'))
    if not Path(project['video']).is_file():
        raise ValueError('Falta el vídeo incluido de ' + stadium + '. Reinstala la carpeta completa de la app.')
    project.update(stadium=stadium, trim_start=0, duration=15)
    return apply_team_layout(project)


def bind_stadium(project, runtime):
    """Saved projects may customize graphics, never replace the bundled movie."""
    project = copy.deepcopy(project)
    base = stadium_project(runtime, project['stadium'])
    previous = float(project.get('duration', 15))
    if previous <= 0 or not math.isfinite(previous):
        raise ValueError('La duración guardada no es válida.')
    for item in project['elements']:
        if previous != 15:
            for field in ('start', 'end', 'fade'):
                item[field] *= 15/previous
            for key in item['keys']:
                key['time'] *= 15/previous
    project.update(video=base['video'], trim_start=0, duration=15)
    return apply_team_layout(project)


def rectangle(x, y, width, height):
    return [[x, y], [x + width, y], [x, y + height], [x + width, y + height]]


def layer(kind='text', name='Texto', text='', path='', start=0, end=17,
          box=(25, 35, 50, 18), enabled=True):
    return dict(id=uuid.uuid4().hex, kind=kind, name=name, enabled=enabled,
                text=text, path=path, color='#ffffff', start=start, end=end, fade=.4,
                keys=[dict(time=0, corners=rectangle(*box))])


def defaults():
    return dict(kind='stadium_cinematic', version=1, stadium='Champions Field', name='Nueva toma de estadio',
                video='', trim_start=0, duration=17,
                variables=dict(torneo='TORNEO PIRULETA', ronda='GRAN FINAL',
                               equipo_a='Equipo A', equipo_b='Equipo B',
                               jugadores_a='', jugadores_b=''),
                elements=[
                    layer(name='Torneo', text='{torneo}', start=0, end=4, box=(15, 35, 70, 15)),
                    layer(name='Ronda', text='{ronda}', start=4, end=7, box=(20, 35, 60, 15)),
                    layer('image', 'Escudo A', start=7, end=17, box=(22, 40, 18, 32), enabled=False),
                    layer('image', 'Escudo B', start=7, end=17, box=(60, 40, 18, 32), enabled=False),
                    layer(name='Equipo A', text='{equipo_a}', start=7, end=17, box=(12, 75, 38, 8)),
                    layer(name='Equipo B', text='{equipo_b}', start=7, end=17, box=(50, 75, 38, 8)),
                ])


def text_value(text, variables):
    return re.sub(r'\{([a-z_]+)\}', lambda match: str(variables.get(match[1], match[0])), text)


def corners_at(item, seconds):
    keys = sorted(item['keys'], key=lambda key: key['time'])
    if seconds <= keys[0]['time']:
        return copy.deepcopy(keys[0]['corners'])
    for left, right in zip(keys, keys[1:]):
        if seconds <= right['time']:
            amount = (seconds - left['time']) / (right['time'] - left['time'])
            return [[a + (b-a)*amount for a, b in zip(p, q)]
                    for p, q in zip(left['corners'], right['corners'])]
    return copy.deepcopy(keys[-1]['corners'])


def set_key(item, seconds, corners):
    seconds = round(float(seconds), 3)
    item['keys'] = [key for key in item['keys'] if abs(key['time'] - seconds) > .001]
    item['keys'].append(dict(time=seconds, corners=copy.deepcopy(corners)))
    item['keys'].sort(key=lambda key: key['time'])


def validate(project):
    if project.get('kind') != 'stadium_cinematic':
        raise ValueError('Selecciona una configuración de cinemática del estadio.')
    if project.get('stadium') not in STADIUMS:
        raise ValueError('Elige Champions Field, Mannfield o Estadio DFH.')
    if not str(project.get('name', '')).strip():
        raise ValueError('Escribe un nombre para identificar esta toma o mapa.')
    if not isinstance(project.get('variables'), dict):
        raise ValueError('Los textos de la cinemática no son válidos.')
    duration = float(project['duration'])
    trim = float(project['trim_start'])
    if not math.isfinite(duration) or not 1 <= duration <= 120 or not math.isfinite(trim) or trim < 0:
        raise ValueError('Usa una duración de 1 a 120 segundos y un inicio de toma positivo o cero.')
    source_duration = mp4_duration(project['video'])
    if trim + duration > source_duration + .05:
        raise ValueError(f'El tramo elegido supera la duración de la toma ({source_duration:.2f} s).')
    elements = project.get('elements')
    if not isinstance(elements, list) or len(elements) > 40:
        raise ValueError('La cinemática admite hasta 40 elementos.')
    identifiers = set()
    for item in elements:
        if not re.fullmatch(r'[a-f0-9]{32}', str(item.get('id', ''))) or item['id'] in identifiers:
            raise ValueError('Identificador de elemento duplicado o inválido.')
        identifiers.add(item['id'])
        if item.get('kind') not in ('text', 'image'):
            raise ValueError('Solo se admiten textos e imágenes.')
        if not item.get('enabled', True):
            continue
        start, end, fade = (float(item[key]) for key in ('start', 'end', 'fade'))
        if not all(math.isfinite(x) for x in (start, end, fade)) or not 0 <= start < end <= duration or not 0 <= fade <= (end-start)/2:
            raise ValueError(f'{item["name"]}: revisa entrada, salida y fundido dentro de los {duration:g} segundos.')
        if item['kind'] == 'image':
            path = Path(item['path'])
            if not path.is_file() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                raise ValueError(f'{item["name"]}: selecciona una imagen PNG o JPG.')
        elif not text_value(str(item.get('text', '')), project['variables']).strip():
            raise ValueError(f'{item["name"]}: escribe un texto o desactiva el elemento.')
        if len(str(item.get('text', ''))) > 500 or not re.fullmatch(r'#[a-fA-F0-9]{6}', item.get('color', '')):
            raise ValueError('El texto admite 500 caracteres y el color debe ser #RRGGBB.')
        keys = item.get('keys', [])
        if not keys or len(keys) > 500:
            raise ValueError('Cada elemento necesita entre 1 y 500 puntos de seguimiento.')
        times = []
        for key in keys:
            time = float(key['time'])
            if not math.isfinite(time) or not 0 <= time <= duration or len(key['corners']) != 4:
                raise ValueError('Punto de seguimiento fuera de la duración o sin sus cuatro esquinas.')
            times.append(time)
            for point in key['corners']:
                if len(point) != 2 or not all(math.isfinite(float(v)) and -200 <= float(v) <= 300 for v in point):
                    raise ValueError('Las esquinas deben expresarse como porcentajes entre -200 y 300.')
            # Reject degenerate/crossed quads; TL, TR, BL, BR are the editing order.
            points = [key['corners'][i] for i in (0, 1, 3, 2)]
            turns = []
            for i in range(4):
                a, b, c = (points[(i+j) % 4] for j in range(3))
                turns.append((b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]))
            if not (all(v > .001 for v in turns) or all(v < -.001 for v in turns)):
                raise ValueError(f'{item["name"]}: las cuatro esquinas deben formar un cuadrilátero sin cruces.')
        if len(set(times)) != len(times):
            raise ValueError('No puede haber dos puntos de seguimiento en el mismo instante.')
    return project


def load(path):
    path = Path(path)
    project = json.loads(path.read_text(encoding='utf-8-sig'))
    if project.get('kind') != 'stadium_cinematic':
        raise ValueError('Este JSON no es una cinemática del estadio.')
    for item in [project] + [item for item in project['elements'] if item['kind'] == 'image']:
        field = 'video' if item is project else 'path'
        if item.get(field):
            item[field] = str((path.parent / item[field]).resolve())
    return project


def save(project, path):
    Path(path).write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')
