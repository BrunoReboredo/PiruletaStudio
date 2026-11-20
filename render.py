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
    for name in ('Plantilla.blend', 'models.blend', 'blender_job.py', 'paint_finishes.py'):
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
    # Generated projects and logs belong to the library, not the delivery folder.
    work = library.root/'trabajos'/output.name
    work.mkdir(parents=True,exist_ok=True)
    reused = []
    for key in ('field', 'pre', 'victory0', 'victory1'):
        if clips[key] is not None:
            reused.append(key)
            report('Reutilizando '+NAMES[key]+' de la biblioteca · sin render')
    if clips['field'] is None:
        folder = work/'trabajo_field'
        folder.mkdir()
        report('Generando Campo · exportación rápida')
        video = field.render(profile, folder, report, cancelled)
        clips['field'] = library.save_clip(keys['field'], video, dict(engine='fast', kind='Campo'))
    car_clips = {key: name for key, name in
                 (('pre', 'Prepartido'), ('victory0', 'Victoria_A'), ('victory1', 'Victoria_B'))
                 if clips[key] is None}
    if car_clips:
        folder = work/'trabajo_coches'
        folder.mkdir()
        config = dict(template=str(ROOT/'vendor/animations/Plantilla.blend'), output=str(folder),
                      winner='A', victory_header=profile.get('victory_header', profile['event']),
                      video=True, resolution=100, render_clips=list(car_clips.values()),
                      engine=profile.get('render_engine', 'EEVEE'),
                      paint_finish=profile.get('paint_finish', 'Brillante'),
                      teams={letter: copy.deepcopy(team) for letter, team in zip(('A', 'B'), profile['teams'])})
        report('Generando '+', '.join(NAMES[key] for key in car_clips)+' · '+config['engine'])
        try:
            run_job(blender, config, folder, cancelled)
        finally:
            # Completed clips survive a later render failure or cancellation.
            for key, name in car_clips.items():
                video = folder/(name+'.mp4')
                if video.is_file():
                    clips[key] = library.save_clip(keys[key], video,
                                                   dict(engine=config['engine'], kind=name))
                    report(NAMES[key]+' guardado en la biblioteca')
        if any(clips[key] is None for key in car_clips):
            raise RuntimeError('Blender no ha completado todos los vídeos solicitados.')
    if cancelled.is_set():
        raise RuntimeError('Preparación cancelada. Los vídeos completos se conservan en la biblioteca.')
    files = {}
    for key, clip in clips.items():
        target = output/(NAMES[key]+'.mp4')
        pending=output/(target.name+'.tmp')
        try:
            shutil.copy2(clip['path'],pending)
            os.replace(pending,target)
        finally:
            pending.unlink(missing_ok=True)
        files[key] = str(target)
    manifest = dict(fingerprint=signature, files=files, source='blender',
                    engine=profile.get('render_engine', 'EEVEE'), reused=reused,
                    durations={key: clip['duration'] for key, clip in clips.items()})
    manifest['delivery'] = str(output.resolve())
    manifest_path = work/'manifest.json'
    atomic_json(manifest_path, manifest)
    index_path = library.root/'preparaciones.json'
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
        if not isinstance(index,dict):
            index = {}
    except (OSError,ValueError):
        index = {}
    index[str(output.resolve())] = str(manifest_path)
    atomic_json(index_path,index)
    return manifest

def load_preparation(path, library_dir):
    """Select any delivered MP4; read its metadata from the internal library."""
    path = Path(path).resolve()
    if path.suffix.lower() == '.json':
        return json.loads(path.read_text(encoding='utf-8-sig'))
    if path.suffix.lower() != '.mp4':
        raise ValueError('Selecciona un MP4 de la preparación o un manifest.json antiguo.')
    try:
        index = json.loads((Path(library_dir)/'preparaciones.json').read_text(encoding='utf-8'))
        return json.loads(Path(index[str(path.parent)]).read_text(encoding='utf-8'))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise ValueError('No se encuentra la preparación interna. Puedes importar los cuatro MP4 como vídeos propios.') from exc
