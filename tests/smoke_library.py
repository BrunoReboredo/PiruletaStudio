"""Real EEVEE/cache integration with two-frame clips, isolated from the user library."""
import copy
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import render
from studio import defaults

root = Path(__file__).resolve().parents[1]
profile = defaults()
for i, team in enumerate(profile['teams']):
    team.update(name='Prueba '+str(i+1), short='P'+str(i+1),
                logo=str(root/'vendor/overlay/assets/torneo.png'))
destination = root/'data/smoke_library'
# A fresh, private library prevents abbreviated QA clips from being used on air.
from datetime import datetime
library = destination/('biblioteca_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
original_runner = render.run_job
calls = []
def limited_runner(blender, config, folder, cancelled):
    config = copy.deepcopy(config)
    config.update(test_frames=2, samples=32, preview_resolution=50)
    calls.append(config['only_scenes'][0])
    original_runner(blender, config, folder, cancelled)

with patch('render.run_job', side_effect=limited_runner):
    first = render.prepare(profile, destination, print, threading.Event(), library_dir=library)
    assert len(calls) == 3
    second = render.prepare(profile, destination, print, threading.Event(), library_dir=library)
    assert len(calls) == 3, 'La segunda preparación no debe volver a ejecutar Blender.'
    assert len(second['reused']) == 3
    assert all(Path(p).is_file() for p in second['files'].values())
print('EEVEE 1080p + caché real: tres vídeos renderizados y tres reutilizados sin ejecutar Blender.', flush=True)
