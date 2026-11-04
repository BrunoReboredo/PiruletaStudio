"""Optional real Blender integration check: tiny videos, both possible winners."""
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import defaults

ROOT = Path(__file__).resolve().parents[1]
p = defaults()
engine = 'CYCLES' if '--cycles' in sys.argv else 'EEVEE'
for i, team in enumerate(p['teams']):
    team.update(name='Equipo '+str(i+1), short='E'+str(i+1),
                logo=str(ROOT/'vendor/overlay/assets/torneo.png'), car='Dominus' if i == 0 else 'Fennec')
for winner in ('A', 'B'):
    folder = ROOT/('data/smoke_'+engine)/winner
    folder.mkdir(parents=True, exist_ok=True)
    config = dict(template=str(ROOT/'vendor/animations/Plantilla.blend'), output=str(folder),
                  winner=winner, victory_header=p['event'], video=True, resolution=100 if engine=='EEVEE' else 10,
                  engine=engine, preview_resolution=50, samples=32 if engine=='EEVEE' else 1,
                  test_frames=2, only_victory=winner=='B',
                  teams={key: copy.deepcopy(team) for key, team in zip(('A', 'B'), p['teams'])})
    job = folder/'job.json'
    job.write_text(json.dumps(config), encoding='utf-8')
    with (folder/'blender.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([p['blender'], '--background', '--python-exit-code', '1', '--python',
                                 str(ROOT/'vendor/animations/blender_job.py'), '--', str(job)], stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((folder/'blender.log').read_text(encoding='utf-8')[-6000:])
        raise SystemExit(result.returncode)
    expected = ('Victoria', 'Prepartido') if winner == 'A' else ('Victoria',)
    for name in expected:
        assert (folder/(name+'.mp4')).is_file(), name
        assert (folder/(name+'.png')).is_file(), name
    print('Blender: '+winner+' OK', flush=True)
