"""Read source-associated team logos independently of manual postmatch crests."""
import base64
import hashlib
from urllib.parse import urlsplit

MAX_BYTES = 12_000_000


def image_bytes(value):
    if isinstance(value, str) and value.startswith('data:'):
        try:
            header, encoded = value.split(',', 1)
            if header not in ('data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64') or len(encoded) > MAX_BYTES*4//3+4:
                return None
            value = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return None
    if not isinstance(value, (bytes, bytearray, memoryview)) or not 12 <= len(value) <= MAX_BYTES:
        return None
    value = bytes(value)
    if value.startswith(b'\x89PNG\r\n\x1a\n') and len(value) >= 24:
        return value, 'image/png'
    if value.startswith(b'\xff\xd8\xff'):
        return value, 'image/jpeg'
    if value[:4] == b'RIFF' and value[8:12] == b'WEBP':
        return value, 'image/webp'
    return None


def source_team_logos(dataset, config, teams, cache):
    from .data_sources import auto_mapping, token
    mapping = auto_mapping(dataset['headers'])
    mapping.update({k: v for k, v in config.get('mapping', {}).items() if v or k == 'Name'})
    result = []
    for team in teams:
        logo = ''
        for row in dataset['rows']:
            if token(row.get(mapping.get('Team'), '')) != token(team['name']):
                continue
            value = row.get(mapping.get('Logo'))
            decoded = image_bytes(value)
            if decoded:
                data, mime = decoded
                identity = hashlib.sha256(data).hexdigest()
                cache.pop(identity, None)
                cache[identity] = (data, mime)
                logo = '/prematch-logo/'+identity
                break
            if isinstance(value, str):
                url = urlsplit(value.strip())
                if url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password:
                    logo = value.strip()
                    break
        result.append(logo)
    # Retain recent pairs through fades without growing across an entire tournament.
    while len(cache) > 8 or sum(len(data) for data, _ in cache.values()) > 32_000_000:
        cache.pop(next(iter(cache)))
    return result
