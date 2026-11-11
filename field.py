"""Use the individual animation app's fast stadium compositor."""
from pathlib import Path
import hashlib
import copy
ROOT = Path(__file__).resolve().parent/'vendor/animations'
LOGO_START_SECONDS = 6
def signature():
    h=hashlib.sha256(f'logo-start={LOGO_START_SECONDS}'.encode('ascii'))
    for name in ('cinema.py','cinema_fast.py','cinema_preview.py','stadium_layout.py'):
        h.update((ROOT/name).read_bytes())
    for p in sorted((ROOT/'assets/stadiums').glob('*')):
        h.update(p.read_bytes())
    return h.hexdigest()
def project(profile):
    from vendor.animations.cinema import stadium_project
    p=stadium_project(ROOT,profile.get('stadium','Champions Field'))
    p['variables'].update(torneo=profile['event'],ronda=profile['round'],
        equipo_a=profile['teams'][0]['name'],equipo_b=profile['teams'][1]['name'])
    for side, team in zip(('A','B'),profile['teams']):
        for item in p['elements']:
            if item['kind']=='image' and item['name']=='Escudo '+side:
                item.update(path=team['logo'], enabled=True, start=LOGO_START_SECONDS)
    return p
def render(profile, folder, report, cancelled):
    from vendor.animations.cinema_fast import export
    export(dict(project=project(profile),time=8),folder,cancelled,report,lambda process: None)
    return Path(folder)/'Apertura.mp4'
