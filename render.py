"""Render only missing clips; reuse matching, verified library videos."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
import uuid
from studio import fingerprint
import field
from library import Library, atomic_json, clip_keys, file_hash

ROOT = Path(__file__).resolve().parent
NAMES = dict(field='Campo', pre='Prepartido', victory0='Victoria_A', victory1='Victoria_B')


def renderer_signature():
    digest = hashlib.sha256()
    for name in ('Plantilla.blend', 'models.blend', 'blender_job.py'):
        digest.update(file_hash(ROOT/'vendor/animations'/name).encode())
    return digest.hexdigest()


def cached_clips(profile, library_dir):
    library = Library(library_dir)
    keys = clip_keys(profile, renderer_signature(), field.signature())
    return {key: library.clip(value) for key, value in keys.items()}


def run_job(blender, config, folder, cancelled):
    if cancelled.is_set():
        raise RuntimeError('Preparación cancelada.')
    job = folder/'job.json'
    atomic_json(job, config)
    command = [str(blender), '--background', '--python-exit-code', '1', '--python',
               str(ROOT/'vendor/animations/blender_job.py'), '--', str(job)]
    with (folder/'registro.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        while process.poll() is None:
            if cancelled.wait(.2):
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise RuntimeError('Preparación cancelada. Los vídeos completos se conservan en la biblioteca.')
        if process.returncode:
            raise RuntimeError('Blender no pudo preparar la escena. Revisa '+str(folder/'registro.log'))


def prepare(profile, destination, report, cancelled, library_dir=None):
    library = Library(library_dir or Path(destination)/'biblioteca')
    signature = fingerprint(profile)
    profile = library.import_profile(profile)
    keys = clip_keys(profile, renderer_signature(), field.signature())
    clips = {key: library.clip(value) for key, value in keys.items()}
    missing = [key for key, clip in clips.items() if clip is None]
    blender = Path(profile['blender'])
    if any(key != 'field' for key in missing) and not blender.is_file():
        raise ValueError('Faltan vídeos en la biblioteca. Selecciona Blender para generar solo los que faltan.')
    output = Path(destination)/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    reused = []
    for key in ('field','pre', 'victory0', 'victory1'):
        if cancelled.is_set():
            raise RuntimeError('Preparación cancelada. Los vídeos completos se conservan en la biblioteca.')
        if clips[key] is not None:
            reused.append(key)
            report('Reutilizando '+NAMES[key]+' de la biblioteca · sin render')
            continue
        folder = output/('trabajo_'+key)
        folder.mkdir()
        if key == 'field':
            report('Generando Campo · exportación rápida')
            video = field.render(profile, folder, report, cancelled)
            clips[key] = library.save_clip(keys[key], video, dict(engine='fast',kind='Campo'))
            continue
        if key == 'pre':
            teams = {letter: copy.deepcopy(team) for letter, team in zip(('A', 'B'), profile['teams'])}
            scene = 'Prepartido'
        else:
            # Canonical winner A makes the victory independent of opponent or side.
            winner = profile['teams'][int(key[-1])]
            teams = {letter: copy.deepcopy(winner) for letter in ('A', 'B')}
            scene = 'Victoria'
        config = dict(template=str(ROOT/'vendor/animations/Plantilla.blend'), output=str(folder),
                      winner='A', victory_header=profile['event'], video=True, resolution=100,
                      engine=profile.get('render_engine', 'EEVEE'), only_scenes=[scene], teams=teams)
        report('Generando '+NAMES[key]+' · '+config['engine'])
        run_job(blender, config, folder, cancelled)
        clips[key] = library.save_clip(keys[key], folder/(scene+'.mp4'),
                                       dict(engine=config['engine'], kind=scene))
        report(NAMES[key]+' guardado en la biblioteca')
    files = {}
    for key, clip in clips.items():
        target = output/(NAMES[key]+'.mp4')
        shutil.copy2(clip['path'], target)
        files[key] = str(target)
    manifest = dict(fingerprint=signature, files=files, source='blender',
                    engine=profile.get('render_engine', 'EEVEE'), reused=reused,
                    durations={key: clip['duration'] for key, clip in clips.items()})
    atomic_json(output/'manifest.json', manifest)
    return manifest
