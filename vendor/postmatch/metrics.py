"""Metric catalogue, sampled match telemetry and persistent series/tournament history."""
import copy
import json
import math
import time
import uuid
from .roster import player_key

CATALOG = []


def group(name, entries):
    for key, label, unit, aggregate in entries:
        CATALOG.append(dict(key=key, label=label, group=name, unit=unit, aggregate=aggregate))


group('Básicas', [(k, n, '', 'sum') for k, n in [
    ('Score', 'Puntos'), ('Goals', 'Goles'), ('Assists', 'Asistencias'), ('Shots', 'Tiros'),
    ('Saves', 'Salvadas'), ('Touches', 'Toques de balón'), ('CarTouches', 'Contactos entre coches'),
    ('Demos', 'Demoliciones'), ('BoostUsed', 'Turbo usado')]])
group('Ataque y puntuación', [
    ('Accuracy', 'Acierto de tiro', '%', 'ratio'), ('Participation', 'Participación en goles', '%', 'ratio'),
    ('ShotsPerMinute', 'Tiros por minuto', '/min', 'ratio'),
    ('PointsPerMinute', 'Puntos por minuto', '/min', 'ratio'),
    ('PointsShare', 'Porcentaje de puntos del equipo', '%', 'ratio')])
group('Movimiento', [('SpeedAvg', 'Velocidad media', 'km/h', 'mean'), ('SpeedMax', 'Velocidad máxima', 'km/h', 'max')])
for key, label in [('Supersonic', 'Supersónico'), ('Ground', 'En suelo'), ('Wall', 'En pared'), ('Powerslide', 'Derrapando')]:
    group('Movimiento', [(key+'Time', 'Tiempo '+label.lower(), 's', 'sum'),
                         (key+'Pct', label+' (%)', '%', 'ratio')])
group('Turbo', [('BoostAvg', 'Turbo medio', '%', 'mean'), ('BoostZeroTime', 'Tiempo sin turbo', 's', 'sum'),
    ('BoostFullTime', 'Tiempo con turbo a 100', 's', 'sum'), ('BoostingTime', 'Tiempo usando turbo', 's', 'sum'),
    ('SmallPads', 'Recogidas pequeñas', '', 'sum'), ('BigPads', 'Recogidas grandes', '', 'sum'),
    ('BoostCollected', 'Turbo recogido', '', 'sum')])
group('Demoliciones', [('DemosReceived', 'Demoliciones recibidas', '', 'sum'),
    ('DemoBalance', 'Balance de demoliciones', '', 'sum'),
    ('DemoMatchups', 'Demoliciones por rival', 'texto', 'text')])
group('Balón', [('TouchesPerMinute', 'Toques por minuto', '/min', 'ratio'),
    ('TouchShare', 'Reparto de toques del equipo', '%', 'ratio'),
    ('HitSpeedAvg', 'Velocidad media de golpeos', 'km/h', 'mean'),
    ('HitSpeedMax', 'Velocidad máxima de golpeo', 'km/h', 'max')])
group('Goles', [('GoalSpeedMax', 'Gol más rápido', 'km/h', 'max'),
    ('GoalSpeedAvg', 'Velocidad media de goles', 'km/h', 'mean'),
    ('FirstGoal', 'Primer goleador', 'sí/no', 'sum'), ('OvertimeGoals', 'Goles en prórroga', '', 'sum')])
group('Serie y torneo', [('Matches', 'Partidos jugados', '', 'count'), ('Wins', 'Victorias', '', 'count'),
    ('Losses', 'Derrotas', '', 'count'), ('GoalDiff', 'Diferencia de goles', '', 'sum'),
    ('WinRate', 'Porcentaje de victorias', '%', 'ratio'), ('Ranking', 'Posición', 'puesto', 'rank')])
for key, label in [('Score', 'Puntos'), ('Goals', 'Goles'), ('Assists', 'Asistencias'), ('Shots', 'Tiros'),
                   ('Saves', 'Salvadas'), ('Touches', 'Toques'), ('Demos', 'Demoliciones'), ('BoostUsed', 'Turbo usado')]:
    group('Serie y torneo', [(key+'PerGame', label+' por partido', '/partido', 'mean')])

DEFAULT_METRICS = ['Score', 'Goals', 'Assists', 'Shots', 'Saves', 'BoostUsed']
METRIC_KEYS = {m['key'] for m in CATALOG}
DIRECT = ['Score', 'Goals', 'Assists', 'Shots', 'Saves', 'Touches', 'CarTouches', 'Demos', 'BoostUsed']


def identity(p):
    return player_key(p)


def historical_row(record, player, players):
    rows = record.get('rows', {})
    key = identity(player)
    if key in rows:
        return rows[key]
    primary, name = player.get('PrimaryId'), player.get('Name')
    unique_id = primary and sum(p.get('PrimaryId') == primary for p in players) == 1
    # Read 1.0 histories too, while refusing ambiguous shared platform identifiers.
    if unique_id and str(primary) in rows:
        return rows[str(primary)]
    if name and sum(p.get('Name') == name for p in players) == 1:
        if name in rows:
            return rows[name]
        candidates = []
        for saved_key, row in rows.items():
            try:
                parts = json.loads(saved_key)
            except (ValueError, TypeError):
                continue
            if isinstance(parts, list) and len(parts) == 3 and parts[1] == name and parts[0] == primary:
                candidates.append(row)
        if len(candidates) == 1:
            return candidates[0]
    return None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ratio(a, b, scale=1):
    return a/b*scale if number(a) and number(b) and b > 0 else None


def add(row, key, value):
    row[key] = row.get(key, 0) + value


def merge(rows):
    result = {'results': {}, 'victims': {}}
    for row in rows:
        for key, value in row.items():
            if key in ('results', 'victims'):
                for name, item in value.items():
                    if key == 'results':
                        result[key][name] = item
                    else:
                        result[key][name] = result[key].get(name, 0)+item
            elif number(value):
                result[key] = max(result.get(key, value), value) if key.endswith('Max') else result.get(key, 0)+value
    return result


def values(row, team):
    out = {key: row.get(key) for key in DIRECT}
    seconds = row.get('Seconds', 0)
    out.update(Accuracy=ratio(row.get('Goals'), row.get('Shots'), 100),
        Participation=ratio((row.get('Goals', 0)+row.get('Assists', 0)), team.get('Goals'), 100),
        ShotsPerMinute=ratio(row.get('Shots'), seconds, 60),
        PointsPerMinute=ratio(row.get('Score'), seconds, 60),
        PointsShare=ratio(row.get('Score'), team.get('Score'), 100),
        TouchesPerMinute=ratio(row.get('Touches'), seconds, 60),
        TouchShare=ratio(row.get('Touches'), team.get('Touches'), 100),
        SpeedAvg=ratio(row.get('SpeedIntegral'), row.get('SpeedSeconds')),
        SpeedMax=row.get('SpeedMax'), BoostAvg=ratio(row.get('BoostIntegral'), row.get('BoostSeconds')),
        HitSpeedAvg=ratio(row.get('HitSpeedSum'), row.get('HitCount')), HitSpeedMax=row.get('HitSpeedMax'),
        GoalSpeedAvg=ratio(row.get('GoalSpeedSum'), row.get('GoalCount')), GoalSpeedMax=row.get('GoalSpeedMax'))
    for key in ('Supersonic', 'Ground', 'Wall', 'Powerslide'):
        out[key+'Time'] = row.get(key+'Time')
        out[key+'Pct'] = ratio(row.get(key+'Time'), row.get(key+'Seconds'), 100)
    for key in ('BoostZeroTime', 'BoostFullTime', 'BoostingTime', 'SmallPads', 'BigPads', 'BoostCollected',
                'DemosReceived', 'FirstGoal', 'OvertimeGoals'):
        out[key] = row.get(key)
    out['DemoBalance'] = row.get('Demos', 0)-row.get('DemosReceived', 0) if 'Demos' in row and 'DemosReceived' in row else None
    out['DemoMatchups'] = ' · '.join(f'{name}: {count}' for name, count in sorted(row.get('victims', {}).items())) or '—'
    results = list(row.get('results', {}).values())
    out.update(Matches=len(results), Wins=sum(r['won'] for r in results),
        Losses=sum(not r['won'] for r in results), GoalDiff=sum(r['gf']-r['ga'] for r in results))
    out['WinRate'] = ratio(out['Wins'], len(results), 100)
    for key in DIRECT:
        out[key+'PerGame'] = ratio(row.get(key), len(results))
    return {k: round(v, 2) if number(v) else v for k, v in out.items()}


class Statistics:
    def __init__(self, clock=time.monotonic, history_file=None):
        self.clock, self.history_file = clock, history_file
        self.history = []
        self.series_id = uuid.uuid4().hex
        if history_file and history_file.exists():
            try:
                data = json.loads(history_file.read_text('utf-8'))
                if isinstance(data.get('records'), list):
                    self.history = data['records']
                    self.series_id = str(data.get('series', self.series_id))
            except (OSError, ValueError, AttributeError):
                pass
        self.reset_match()

    def save(self):
        if self.history_file:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.history_file.with_suffix('.tmp')
            temp.write_text(json.dumps({'series': self.series_id, 'records': self.history}, ensure_ascii=False), 'utf-8')
            temp.replace(self.history_file)

    def new_series(self):
        self.series_id = uuid.uuid4().hex
        self.save()

    def new_tournament(self):
        self.history = []
        self.new_series()

    def reset_match(self):
        self.rows, self.players, self.previous = {}, {}, {}
        self.active, self.replay, self.overtime = True, False, False
        self.last_time = None
        self.first_goal = False

    def boundary(self, active):
        self.active = active
        self.last_time = None
        self.previous = {}

    def record(self, p):
        key = identity(p)
        for existing, known in list(self.players.items()):
            if known.get('Name') == p.get('Name') and known.get('TeamNum') == p.get('TeamNum'):
                if not p.get('PrimaryId'):
                    key = existing
                elif existing != key:
                    self.rows[key] = self.rows.pop(existing)
                    self.players[key] = self.players.pop(existing)
                break
        if key not in self.rows:
            self.rows[key] = {'victims': {}, 'results': {}, 'FirstGoal': 0, 'OvertimeGoals': 0,
                'SmallPads': 0, 'BigPads': 0, 'BoostCollected': 0, 'DemosReceived': 0}
        self.players[key] = {**self.players.get(key, {}), **p}
        return self.rows[key]

    def update(self, players, game):
        now = self.clock()
        self.replay, self.overtime = bool(game.get('bReplay')), bool(game.get('bOvertime'))
        if self.replay:
            self.last_time = None
            self.previous = {}
            return
        # Scoreboard updates can arrive after GoalScored, while the round is stopped.
        # Keep those final counters, without integrating stopped car telemetry.
        for p in players:
            row = self.record(p)
            for field in DIRECT:
                if number(p.get(field)):
                    row[field] = p[field]
        if not self.active:
            self.last_time = None
            self.previous = {}
            return
        elapsed = now-self.last_time if self.last_time is not None else 0
        dt = elapsed if 0 <= elapsed <= 2 else 0
        for p in players:
            row = self.record(p)
            for field in DIRECT:
                if number(p.get(field)):
                    row[field] = p[field]
            prior = self.previous.get(identity(p))
            if prior:
                add(row, 'Seconds', dt)
                if prior.get('bHasCar', True) and not prior.get('bDemolished', False):
                    if number(prior.get('Speed')):
                        speed = prior['Speed']*.036
                        add(row, 'SpeedIntegral', speed*dt)
                        add(row, 'SpeedSeconds', dt)
                    if number(prior.get('Boost')):
                        add(row, 'BoostIntegral', prior['Boost']*dt)
                        add(row, 'BoostSeconds', dt)
                        add(row, 'BoostZeroTime', dt if prior['Boost'] == 0 else 0)
                        add(row, 'BoostFullTime', dt if prior['Boost'] == 100 else 0)
                    for field, key in [('bSupersonic', 'Supersonic'), ('bOnGround', 'Ground'),
                        ('bOnWall', 'Wall'), ('bPowersliding', 'Powerslide'), ('bBoosting', 'Boosting')]:
                        # Spectator boolean flags are omitted when false by some clients.
                        if field in prior or 'bHasCar' in prior:
                            add(row, key+'Time', dt if prior.get(field, False) else 0)
                            add(row, key+'Seconds', dt)
            if number(p.get('Speed')) and p.get('bHasCar', True) and not p.get('bDemolished', False):
                row['SpeedMax'] = max(row.get('SpeedMax', 0), p['Speed']*.036)
        self.previous = {identity(p): dict(p) for p in players}
        self.last_time = now

    def event(self, event, data):
        if data.get('bReplay') or self.replay or not self.active:
            return
        if event == 'BoostPickup':
            p = data.get('Player', {})
            if not p.get('Name'):
                return
            row = self.record(p)
            kind = data.get('BoostType', '')
            if kind.endswith('_Pad'):
                add(row, 'SmallPads', 1)
            elif kind.endswith('_Pill'):
                add(row, 'BigPads', 1)
            if number(data.get('BoostAmount')):
                add(row, 'BoostCollected', data['BoostAmount'])
        elif event == 'BallHit':
            speed = data.get('Ball', {}).get('PostHitSpeed')
            if number(speed):
                for p in data.get('Players', []):
                    row = self.record(p)
                    add(row, 'HitSpeedSum', speed*.036)
                    add(row, 'HitCount', 1)
                    row['HitSpeedMax'] = max(row.get('HitSpeedMax', 0), speed*.036)
        elif event == 'GoalScored':
            p = data.get('Scorer', {})
            if p.get('Name'):
                row = self.record(p)
                if not self.first_goal:
                    row['FirstGoal'] = 1
                if self.overtime:
                    add(row, 'OvertimeGoals', 1)
                speed = data.get('GoalSpeed')
                if number(speed):
                    add(row, 'GoalSpeedSum', speed*.036)
                    add(row, 'GoalCount', 1)
                    row['GoalSpeedMax'] = max(row.get('GoalSpeedMax', 0), speed*.036)
                self.first_goal = True
        elif event == 'StatfeedEvent' and data.get('EventName') == 'Demolish':
            attacker, victim = data.get('MainTarget', {}), data.get('SecondaryTarget', {})
            if attacker.get('Name') and victim.get('Name'):
                row = self.record(attacker)
                name = victim['Name']
                row['victims'][name] = row['victims'].get(name, 0)+1
                add(self.record(victim), 'DemosReceived', 1)

    def finish(self, guid, winner, scores):
        guid = guid or uuid.uuid4().hex
        if any(r.get('guid') == guid for r in self.history):
            return
        for key, row in self.rows.items():
            team = self.players[key].get('TeamNum')
            if team in (0, 1):
                row['results'][guid] = dict(won=team == winner, gf=scores[team], ga=scores[1-team])
        self.history.append(dict(guid=guid, series=self.series_id, rows=copy.deepcopy(self.rows)))
        self.save()

    def presentation(self, players, scope='match', team_mode='total'):
        rows = {}
        for p in players:
            key = identity(p)
            if scope == 'match':
                rows[key] = self.rows.get(key, {})
            else:
                records = [row for r in self.history if (scope == 'tournament' or r.get('series') == self.series_id)
                           for row in [historical_row(r, p, players)] if row is not None]
                rows[key] = merge(records)
        teams = [merge([rows[identity(p)] for p in players if p['TeamNum'] == t]) for t in (0, 1)]
        output = []
        for p in players:
            output.append({**p, **values(rows[identity(p)], teams[p['TeamNum']])})
        # Rank against every recorded participant in the selected scope.
        rank_rows = self.rows if scope == 'match' else {
            key: merge([r['rows'][key] for r in self.history if key in r.get('rows', {})
                        and (scope == 'tournament' or r.get('series') == self.series_id)])
            for key in {k for r in self.history for k in r.get('rows', {})}}
        for p in output:
            score = rows[identity(p)].get('Score')
            p['Ranking'] = 1+sum(r.get('Score', -1) > score for r in rank_rows.values()) if number(score) else None
        # Team rates use shared match time instead of summed player time.
        for t in (0, 1):
            member_rows = [rows[identity(p)] for p in players if p['TeamNum'] == t]
            teams[t]['Seconds'] = max((r.get('Seconds', 0) for r in member_rows), default=0)
        team_values = [values(team, team) for team in teams]
        for t in (0, 1):
            score, other = teams[t].get('Score'), teams[1-t].get('Score')
            team_values[t]['Ranking'] = 1+int(other > score) if number(score) and number(other) else None
        if team_mode == 'mean':
            for t in (0, 1):
                n = sum(p['TeamNum'] == t for p in players)
                for metric in CATALOG:
                    key = metric['key']
                    if metric['aggregate'] == 'sum' and number(team_values[t].get(key)) and n:
                        team_values[t][key] /= n
        elif team_mode in ('difference', 'share'):
            for metric in CATALOG:
                key = metric['key']
                a, b = (v.get(key) for v in team_values)
                if number(a) and number(b):
                    pair = [a-b, b-a] if team_mode == 'difference' else [ratio(a, a+b, 100), ratio(b, a+b, 100)]
                    for t in (0, 1):
                        team_values[t][key] = pair[t]
        return output, team_values
