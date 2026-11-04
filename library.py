"""Content-addressed local assets and verified, reusable rendered clips."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
from media import mp4_duration
from studio import detect_decal


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()

    def store_asset(self, source, kind, car=None):
        source = Path(source).resolve()
        digest = file_hash(source)
        if kind not in ('logos', 'calcomanias'):
            raise ValueError('Tipo de recurso no válido.')
        folder = self.root/kind
        folder.mkdir(parents=True, exist_ok=True)
        target = folder/(digest+source.suffix.lower())
        for existing in folder.glob(digest+'.*'):
            if existing.is_file() and file_hash(existing) == digest:
                target = existing
                break
        # The name is the content hash. Verify an existing copy before trusting it.
        if target != source and (not target.is_file() or file_hash(target) != digest):
            temporary = folder/(uuid.uuid4().hex+'.tmp')
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        with self.lock:
            catalog_path = self.root/'catalogo.json'
            try:
                catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
                if not isinstance(catalog, dict):
                    catalog = {}
            except (OSError, ValueError):
                catalog = {}
            key = kind+'/'+digest
            entry = catalog.get(key, {})
            if not isinstance(entry, dict):
                entry = {}
            names = set(entry.get('nombres', []))
            if source != target:
                names.add(source.name)
            catalog[key] = dict(archivo=str(target.relative_to(self.root)), sha256=digest,
                               nombres=sorted(names), coche=car)
            atomic_json(catalog_path, catalog)
        return str(target)

    def import_profile(self, profile):
        """Call after validation; assets now survive removal of their original files."""
        result = copy.deepcopy(profile)
        for team in result['teams']:
            team['logo'] = self.store_asset(team['logo'], 'logos')
            if team.get('skin'):
                known = detect_decal(team['skin'])
                team['skin'] = self.store_asset(team['skin'], 'calcomanias', known or team['car'])
                # Filename model hints are lost in a hashed filename. Preserve the
                # already validated compatibility, without guessing unknown images.
                if known == team['car']:
                    team['skin_confirmed'] = team['car']
        return result

    def clip(self, key):
        folder = self.root/'videos'/key
        try:
            metadata = json.loads((folder/'clip.json').read_text(encoding='utf-8'))
            video = folder/'video.mp4'
            if metadata['key'] != key or metadata['sha256'] != file_hash(video):
                return None
            duration = mp4_duration(video)
            return dict(path=str(video), duration=duration, key=key)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_clip(self, key, source, details):
        duration = mp4_duration(source)
        folder = self.root/'videos'/key
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder/(uuid.uuid4().hex+'.tmp')
        shutil.copyfile(source, temporary)
        os.replace(temporary, folder/'video.mp4')
        metadata = dict(key=key, sha256=file_hash(folder/'video.mp4'), duration=duration, **details)
        atomic_json(folder/'clip.json', metadata)
        return dict(path=str(folder/'video.mp4'), duration=duration, key=key)


def team_signature(team):
    return dict(name=team['name'], short=team['short'], car=team['car'], color=team['color'].lower(),
                logo=file_hash(team['logo']), skin=file_hash(team['skin']) if team.get('skin') else None)


def clip_keys(profile, renderer_signature):
    teams = [team_signature(team) for team in profile['teams']]
    shared = dict(schema=1, renderer=renderer_signature,
                  engine=profile.get('render_engine', 'EEVEE'), resolution=100)
    specifications = {
        'pre': dict(kind='pre', teams=teams, header=profile['event']),
        'victory0': dict(kind='victory', team=teams[0], header=profile['event']),
        'victory1': dict(kind='victory', team=teams[1], header=profile['event']),
    }
    return {key: hashlib.sha256(json.dumps(dict(**shared, **spec), sort_keys=True).encode()).hexdigest()
            for key, spec in specifications.items()}
