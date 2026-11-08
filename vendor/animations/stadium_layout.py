"""Project team graphics onto the pitch along the three recorded camera paths."""
import math
import re


def player_names(value):
    value = str(value).strip()
    if not value:
        return []
    return [name.strip() for name in re.split(r'[,;|\n]+', value) if name.strip()] if re.search(r'[,;|\n]', value) else value.split()


def camera_position(t, stadium):
    points = [(0, (-6500, 0, 3500)), (3, (-6200, -1200, 3300)),
              (6, (-4800, -3500, 2700)), (9, (-6200, -4000, 4300)),
              (12, (-3600, -1600, 6800)), (15, (-800, 0, 7900))]
    if stadium == 'Mannfield':
        points[3:5] = [(9, (-3800, -3000, 4300)), (12, (-2000, -800, 6800))]
    if t <= 0:
        return points[0][1]
    if t >= 15:
        return points[-1][1]
    i = next(i for i in range(5) if points[i][0] <= t < points[i+1][0])
    a, b = points[i:i+2]
    dt = b[0]-a[0]
    u = (t-a[0])/dt
    def tangent(j, k):
        if j in (0, 5):
            return 0
        return (points[j+1][1][k]-points[j-1][1][k])/(points[j+1][0]-points[j-1][0])
    return tuple((2*u**3-3*u**2+1)*a[1][k]+(u**3-2*u**2+u)*dt*tangent(i, k)
                 +(-2*u**3+3*u**2)*b[1][k]+(u**3-u**2)*dt*tangent(i+1, k) for k in range(3))


def projected_keys(stadium, side, center_x, width, height):
    center_y = -2400 if side == 'A' else 2400
    plane = [(center_x+height/2, center_y-width/2, 8), (center_x+height/2, center_y+width/2, 8),
             (center_x-height/2, center_y-width/2, 8), (center_x-height/2, center_y+width/2, 8)]
    keys = []
    for frame in range(151):
        t = frame/10
        cam = camera_position(t, stadium)
        forward = [-cam[0], -cam[1], 40-cam[2]]
        length = math.sqrt(sum(x*x for x in forward))
        forward = [x/length for x in forward]
        right = [-forward[1], forward[0], 0]
        length = math.hypot(*right[:2])
        right = [x/length for x in right]
        up = [forward[1]*right[2]-forward[2]*right[1],
              forward[2]*right[0]-forward[0]*right[2], forward[0]*right[1]-forward[1]*right[0]]
        corners = []
        for p in plane:
            v = [a-b for a, b in zip(p, cam)]
            depth = sum(a*b for a, b in zip(v, forward))
            corners.append([50+50*sum(a*b for a, b in zip(v, right))/depth,
                            50-50*(1920/1080)*sum(a*b for a, b in zip(v, up))/depth])
        keys.append(dict(time=t, corners=corners))
    return keys


def apply_team_layout(project):
    # Twice the original 2200-unit logo width and height. Signatures prevent
    # repeated scaling and preserve manual edits until the roster/map changes.
    from .cinema import layer
    for side, aspect in [('A', 1741/1733), ('B', 1105/905)]:
        names = player_names(project['variables'].get('jugadores_'+side.lower(), ''))
        signature = [2, project['stadium'], names]
        logo = next((x for x in project['elements'] if x['kind'] == 'image' and x['name'] == 'Escudo '+side), None)
        if logo is None:
            continue
        if logo.get('team_layout') != signature:
            logo['keys'] = projected_keys(project['stadium'], side, 1500 if names else 0, 4400, 4400/aspect)
            logo['team_layout'] = signature
        role = 'players_'+side.lower()
        listing = next((x for x in project['elements'] if x.get('layout_role') == role), None)
        if listing is None:
            listing = layer(name='Jugadores '+side, start=7, end=15, enabled=False)
            listing.update(layout_role=role, fade=.25)
            project['elements'].append(listing)
        listing.update(text='\n'.join(names), enabled=bool(names))
        if listing.get('team_layout') != signature:
            # Below the upper logo, leaving a clear gap and staying on the pitch.
            height = min(2200, max(550, len(names)*550))
            listing['keys'] = projected_keys(project['stadium'], side, -2100, 3600, height)
            listing['team_layout'] = signature
    return project
