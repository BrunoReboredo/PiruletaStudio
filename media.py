"""Inspect MP4 metadata without executing media or relying on Blender/ffprobe."""
import hashlib
import math
from pathlib import Path
import struct


def atoms(data):
    pos = 0
    while pos + 8 <= len(data):
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            if pos+16 > len(data):
                raise ValueError('Cabecera MP4 incompleta.')
            size = struct.unpack_from('>Q', data, pos+8)[0]
            header = 16
        elif size == 0:
            size = len(data)-pos
        if size < header or pos+size > len(data):
            raise ValueError('Estructura MP4 dañada.')
        yield kind, data[pos+header:pos+size]
        pos += size


def mp4_duration(path):
    path = Path(path)
    if path.suffix.lower() != '.mp4' or not path.is_file():
        raise ValueError('Selecciona un vídeo MP4 con vídeo H.264.')
    size = path.stat().st_size
    moov, has_type = None, False
    with path.open('rb') as file:
        while file.tell()+8 <= size:
            start = file.tell()
            length, kind = struct.unpack('>I4s', file.read(8))
            header = 8
            if length == 1:
                raw = file.read(8)
                if len(raw) != 8:
                    raise ValueError('Cabecera MP4 incompleta.')
                length, header = struct.unpack('>Q', raw)[0], 16
            elif length == 0:
                length = size-start
            if length < header or start+length > size:
                raise ValueError('El archivo MP4 está incompleto o dañado.')
            if kind == b'ftyp':
                has_type = True
            if kind == b'moov':
                if length > 64_000_000:
                    raise ValueError('Los metadatos del vídeo son demasiado grandes.')
                moov = file.read(length-header)
            file.seek(start+length)
    if not has_type or not moov:
        raise ValueError('No se reconoce un MP4 finalizado. Exporta el vídeo antes de importarlo.')
    duration, video_ok = None, False
    for kind, content in atoms(moov):
        if kind == b'mvhd':
            if len(content) >= 20 and content[0] == 0:
                scale, ticks = struct.unpack_from('>II', content, 12)
            elif len(content) >= 32 and content[0] == 1:
                scale, ticks = struct.unpack_from('>IQ', content, 20)
            else:
                raise ValueError('No se puede leer la duración del MP4.')
            duration = ticks/scale if scale else None
        elif kind == b'trak':
            for child_kind, child in atoms(content):
                if child_kind != b'mdia':
                    continue
                children = dict(atoms(child))
                handler = children.get(b'hdlr', b'')
                if handler[8:12] != b'vide':
                    continue
                minf = dict(atoms(children.get(b'minf', b'')))
                stbl = dict(atoms(minf.get(b'stbl', b'')))
                stsd = stbl.get(b'stsd', b'')
                video_ok |= len(stsd) >= 16 and stsd[12:16] in (b'avc1', b'avc3')
    if not video_ok:
        raise ValueError('El MP4 debe contener vídeo H.264 (no solo audio). Vuelve a exportarlo como H.264.')
    if duration is None or not math.isfinite(duration) or not 0 < duration <= 86400:
        raise ValueError('El vídeo no tiene una duración válida.')
    return duration


def imported_manifest(profile_fingerprint, files):
    if set(files) != {'pre', 'victory0', 'victory1'}:
        raise ValueError('Selecciona prepartido, victoria A y victoria B.')
    paths = {key: str(Path(path).resolve()) for key, path in files.items()}
    durations = {key: mp4_duration(path) for key, path in paths.items()}
    digest = hashlib.sha256()
    for path in paths.values():
        with Path(path).open('rb') as file:
            for chunk in iter(lambda: file.read(1024*1024), b''):
                digest.update(chunk)
    return dict(fingerprint=profile_fingerprint, version=digest.hexdigest(), source='manual',
                files=paths, durations=durations)
