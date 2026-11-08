"""Direct stadium composition and H.264 encoding, without Blender."""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
import cv2
import imageio_ffmpeg
from .cinema_preview import Preview
from .cinema import validate, save
from .media import mp4_duration


def export(job, folder, cancelled, status, process_changed):
    project = copy.deepcopy(job['project'])
    validate(project)
    folder = Path(folder)
    resources = folder/'recursos'
    resources.mkdir(parents=True, exist_ok=True)
    for item in project['elements']:
        if item['kind'] == 'image' and item.get('enabled', True):
            source = Path(item['path'])
            target = resources/(item['id']+source.suffix.lower())
            shutil.copy2(source, target)
            item['path'] = str(target)
    shutil.copy2(project['video'], resources/'Toma_base.mp4')
    project['video'] = str(resources/'Toma_base.mp4')
    capture = cv2.VideoCapture(project['video'])
    fps = capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    if not 1 <= fps <= 240:
        raise ValueError('Velocidad del vídeo no válida.')
    count = round(project['duration']*fps)
    pending = folder/'Apertura.en_proceso.mp4'
    preview = Preview()
    process = None
    try:
        preview.frame(project, float(job.get('time', 0))).save(folder/'Vista_previa.png')
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error',
                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1920x1080',
                   '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264',
                   '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                   '-movflags', '+faststart', str(pending)]
        with (folder/'registro.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            process_changed(process)
            for frame in range(count):
                if cancelled.is_set():
                    raise RuntimeError('Exportación cancelada.')
                image = preview.frame(project, frame/fps, (1920, 1080))
                process.stdin.write(image.tobytes())
                if frame % max(1, round(fps)) == 0:
                    status(f'Exportación rápida de Campo: {100*frame/count:.0f} %')
            process.stdin.close()
            if process.wait() or cancelled.is_set():
                raise RuntimeError('No se completó la codificación. Consulta registro.log.')
        if abs(mp4_duration(pending)-project['duration']) > .05:
            raise RuntimeError('El vídeo está incompleto.')
        portable = copy.deepcopy(project)
        portable['video'] = 'recursos/Toma_base.mp4'
        for item in portable['elements']:
            if item['kind'] == 'image' and item.get('enabled', True):
                item['path'] = 'recursos/'+Path(item['path']).name
        save(portable, folder/'cinematica.json')
        pending.replace(folder/'Apertura.mp4')
        (folder/'completado.json').write_text(json.dumps(dict(fps=fps, duration=count/fps, video=True, engine='fast')), encoding='utf-8')
    finally:
        preview.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait()
        process_changed(None)
        pending.unlink(missing_ok=True)
