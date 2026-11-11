"""Shared series state: a single telemetry stream drives every output."""
import base64
import copy
import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from vendor.postmatch.app import Store, GameConnection, series_state, DEFAULT
from vendor.overlay.app import normalize_config, swap_team_sides, PRIVATE_PLAYLISTS

CARS = ('Octane', 'Fennec', 'Dominus')
PHASES = ('field', 'pre', 'game', 'victory0', 'victory1', 'stats', 'complete')


def defaults():
    return {'bestof': 5, 'event': 'TORNEO PIRULETA', 'round': 'FINAL · PARTIDO [GAME] · BO[SERIE]',
            'blender': r'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe',
            'teams': [dict(name='', short='', logo='', color=color, car=car, skin='')
                      for color, car in zip(('#fa54b7', '#ffd14c'), CARS)],
            'obs_port': 4455, 'api_port': 49123, 'render_engine': 'EEVEE', 'stadium': 'Champions Field', 'paint_finish': 'Brillante'}


def detect_decal(path):
    """Use package metadata before filename hints; never execute or extract a ZIP."""
    path = Path(path)
    found = set()
    unknown_body = False
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            if not any(Path(i.filename).suffix.lower() in ('.png', '.jpg', '.jpeg', '.dds', '.tga')
                       for i in archive.infolist()):
                raise ValueError('El ZIP no contiene imágenes de calcomanía.')
            for info in archive.infolist():
                if info.filename.lower().endswith('.json') and info.file_size <= 1_000_000:
                    try:
                        raw = json.loads(archive.read(info).decode('utf-8-sig'))
                    except (ValueError, UnicodeError):
                        continue
                    def walk(value):
                        nonlocal unknown_body
                        if isinstance(value, dict):
                            for k, v in value.items():
                                if k.casefold() == 'bodyid':
                                    model = {'23': 'Octane', '4284': 'Fennec', '403': 'Dominus'}.get(str(v))
                                    if model:
                                        found.add(model)
                                    else:
                                        unknown_body = True
                                walk(v)
                        elif isinstance(value, list):
                            for item in value:
                                walk(item)
                    walk(raw)
            if unknown_body:
                raise ValueError('Solo se aceptan calcomanías de Octane, Fennec o Dominus; BodyID no compatible.')
    if len(found) > 1:
        raise ValueError('El paquete contiene varios coches. Usa una calcomanía de un solo modelo.')
    if found:
        return found.pop()
    hints = [car for car in CARS if re.search(r'(?i)(?<![a-z])' + car + r'(?![a-z])', path.stem)]
    return hints[0] if len(hints) == 1 else None


def validate(profile):
    p = copy.deepcopy(profile)
    p['render_engine'] = str(p.get('render_engine', 'EEVEE')).upper()
    if p['render_engine'] not in ('EEVEE', 'CYCLES'):
        raise ValueError('Elige EEVEE (rápido) o CYCLES (calidad).')
    if p.get('bestof') not in (1, 2, 3, 4, 5, 7):
        raise ValueError('Elige BO1, BO2, BO3, BO4, BO5 o BO7.')
    if not isinstance(p.get('teams'), list) or len(p['teams']) != 2:
        raise ValueError('Se necesitan dos equipos.')
    for i, team in enumerate(p['teams']):
        for field, limit in (('name', 48), ('short', 8)):
            team[field] = str(team.get(field, '')).strip()
            if not 0 < len(team[field]) <= limit:
                raise ValueError(f'Equipo {i+1}: {field} obligatorio (máximo {limit} caracteres).')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', team.get('color', '')):
            raise ValueError(f'Equipo {i+1}: color inválido. Usa #RRGGBB.')
        if team.get('car') not in CARS:
            raise ValueError('Solo se aceptan Octane, Fennec o Dominus.')
        logo = Path(team.get('logo', ''))
        if not logo.is_file() or logo.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            raise ValueError(f'Equipo {i+1}: selecciona un logo PNG o JPG.')
        content = logo.read_bytes()
        if len(content) > 4_000_000 or not (content.startswith(b'\x89PNG\r\n\x1a\n') or content.startswith(b'\xff\xd8\xff')):
            raise ValueError('El logo debe ser PNG/JPG válido y ocupar menos de 4 MB.')
        if team.get('skin'):
            skin = Path(team['skin'])
            if not skin.is_file() or skin.suffix.lower() not in ('.zip', '.png', '.jpg', '.jpeg', '.dds', '.tga'):
                raise ValueError('Calcomanía no válida. Usa ZIP o imagen.')
            model = detect_decal(skin)
            if model and model != team['car']:
                raise ValueError(f'Equipo {i+1}: la calcomanía es de {model}, pero has elegido {team["car"]}.')
            # Untagged images have no reliable UV/model identifier. Require an explicit confirmation.
            if not model and team.get('skin_confirmed') != team['car']:
                raise ValueError(f'Equipo {i+1}: no se puede identificar el coche de la calcomanía. Confirma su compatibilidad con {team["car"]}.')
    if p.get('stadium', 'Champions Field') not in ('Champions Field','Mannfield','Estadio DFH'):
        raise ValueError('Elige un estadio válido.')
    p.setdefault('stadium', 'Champions Field')
    from vendor.animations.paint_finishes import FINISHES
    p.setdefault('paint_finish','Brillante')
    if p['paint_finish'] not in FINISHES:
        raise ValueError('Selecciona un acabado de pintura válido.')
    for field in ('obs_port', 'api_port'):
        p[field] = int(p.get(field, defaults()[field]))
        if not 1 <= p[field] <= 65535:
            raise ValueError('Puerto fuera de rango.')
    return p


def fingerprint(profile, include_stadium=True):
    data = {k: profile[k] for k in ('teams', 'event', 'round', 'bestof')}
    if include_stadium and profile.get('stadium','Champions Field') != 'Champions Field':
        data['stadium'] = profile['stadium']
    if profile.get('paint_finish','Brillante') != 'Brillante':
        data['paint_finish'] = profile['paint_finish']
    raw = json.dumps(data, sort_keys=True).encode()
    for team in profile['teams']:
        for field in ('logo', 'skin'):
            if team.get(field):
                raw += hashlib.sha256(Path(team[field]).read_bytes()).digest()
    return hashlib.sha256(raw).hexdigest()


class Studio(Store):
    def __init__(self, clock=time.monotonic):
        super().__init__()
        self.clock = clock
        self.phase = 'complete'
        self.deadline = None
        self.paused = None
        self.revision = 0
        self.field_opening = False
        self.field_opening_elapsed = False
        self.generation = 0
        self.playlist_id = None
        self.history_replay = False
        self.gameplay = False
        self.armed = False
        self.result_latched = False
        self.match_number = 0
        self.manual_live = False
        self.stats_seconds = 10
        self.stats_enabled = True
        self.scene_seconds = dict(field=15, pre=13, victory0=4, victory1=4)
        self.animation_order = [0, 1]
        self.history = []
        self.podium_at = None
        self.podium_guid = None
        self.goal_sequence = 0
        self.goal_until = 0
        self.goal_team = 0
        self.goal_armed = True
        self.in_goal_replay = False
        self.pending_victory = None
        self.pending_stats = False
        self.podium_due = None
        self.podium_seen = False
        self.stats_cancelled = False

    def configure(self, profile):
        p = validate(profile)
        with self.lock:
            self.boost_usage.reset()
            self.roster = []
            self.podium_at = None
            self.podium_guid = None
            self.goal_until = 0
            self.goal_armed = True
            self.match_guid = None
            self.profile = p
            self.config = copy.deepcopy(DEFAULT)
            self.config.update(bestof=p['bestof'], event=p['event'], round=p['round'], auto_series=True)
            self.config['api_port'] = p['api_port']
            self.config['show_events'] = True
            for i, team in enumerate(p['teams']):
                mime = 'image/png' if Path(team['logo']).suffix.lower() == '.png' else 'image/jpeg'
                logo = 'data:' + mime + ';base64,' + base64.b64encode(Path(team['logo']).read_bytes()).decode()
                self.config['teams'][i] = dict(name=team['name'], short=team['short'], logo=logo, wins=0)
                self.config['colors']['pink' if i == 0 else 'yellow'] = team['color']
            self.finished.clear()
            self.postmatch = None
            self.match = dict(scores=[0, 0], time=300, overtime=False, players=[], target='', banner='')
            self.match_number = 0
            self.result_latched = False
            self.manual_live = False
            self.gameplay = False
            self.armed = False
            self.animation_order = [0, 1]
            self.generation += 1
            self.transition('complete')

    def transition(self, phase, seconds=None, preserve_pending=False):
        if phase not in PHASES:
            raise ValueError('Escena desconocida.')
        with self.lock:
            if not preserve_pending:
                self.pending_victory = None
                self.pending_stats = False
                self.podium_due = None
            self.phase = phase
            self.field_opening = False
            self.field_opening_elapsed = False
            self.deadline = self.clock() + seconds if seconds is not None else None
            self.paused = None
            self.revision += 1
            self.history.append(phase)

    def start(self, opening='pre'):
        if opening not in ('pre','field'):
            raise ValueError('Elige Campo o Coches para comenzar.')
        with self.lock:
            self.armed = True
            self.transition(opening, 15 if opening == 'field' else self.scene_seconds[opening])
            self.field_opening = opening == 'field'

    def after_stats(self):
        return 'complete' if series_state(self.config)['complete'] else 'game'

    def show_stats(self, timed=False):
        with self.lock:
            if not self.postmatch:
                raise ValueError('Todavía no hay estadísticas de un partido finalizado.')
            self.transition('stats', self.stats_seconds if timed else None)

    def hide_stats(self):
        with self.lock:
            if self.pending_victory:
                self.stats_cancelled = True
                return
            if self.pending_stats:
                self.stats_cancelled = True
                if self.phase == 'game':
                    self.transition(self.after_stats())
            self.pending_stats = False
            self.podium_due = None
            if self.phase == 'stats':
                self.transition(self.after_stats())

    def stats_or_next(self):
        if self.stats_cancelled:
            self.transition(self.after_stats())
        elif self.pending_stats and self.stats_enabled:
            # Keep the game/podium visible until its own event plus three seconds.
            if self.podium_due is not None and self.clock() >= self.podium_due:
                self.transition('stats', self.stats_seconds)
            else:
                self.transition('game', preserve_pending=True)
        elif self.stats_enabled:
            self.transition('stats', self.stats_seconds)
        else:
            self.transition(self.after_stats())

    def tick(self):
        with self.lock:
            if self.pending_stats and not self.stats_enabled:
                self.pending_stats = False
                self.podium_due = None
                if self.phase == 'game':
                    self.transition(self.after_stats())
            if self.deadline is not None and self.clock() >= self.deadline:
                if self.phase in ('pre','field'):
                    completed_field_opening = self.field_opening
                    self.transition('game')
                    self.field_opening_elapsed = completed_field_opening
                elif self.phase.startswith('victory'):
                    self.stats_or_next()
                elif self.phase == 'stats':
                    self.transition(self.after_stats())

            if (self.pending_victory and self.phase == 'game' and self.podium_due is not None
                    and self.clock() >= self.podium_due):
                phase = self.pending_victory
                self.transition(phase, self.scene_seconds[phase])

            if (self.pending_stats and self.phase == 'game' and self.podium_due is not None
                    and self.clock() >= self.podium_due):
                self.transition('stats', self.stats_seconds)

    def duration(self, action):
        with self.lock:
            if action == 'hold':
                if self.deadline is not None:
                    self.paused = max(0, self.deadline - self.clock())
                    self.deadline = None
                elif self.paused is not None:
                    self.deadline = self.clock() + self.paused
                    self.paused = None
            elif action == 'extend':
                if self.paused is not None:
                    self.paused += 10
                elif self.deadline is not None:
                    self.deadline += 10
            elif action == 'cut':
                if self.phase.startswith('victory'):
                    self.stats_or_next()
                elif self.phase in ('pre','field'):
                    self.transition('game')
                elif self.phase == 'stats':
                    self.transition(self.after_stats())

    def ingest(self, packet):
        if not isinstance(packet, dict):
            return False
        event, data = packet.get('Event'), packet.get('Data', {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return False
        if not isinstance(data, dict):
            return False
        with self.lock:
            if event == 'MatchCreated':
                self.podium_at = None
                self.podium_guid = None
                self.goal_armed = True
                self.in_goal_replay = False
                self.goal_until = 0
            elif event in ('ReplayCreated','MatchDestroyed'):
                self.goal_until = 0
            elif event == 'GoalReplayStart':
                self.in_goal_replay = True
                self.goal_armed = False
            elif event == 'GoalReplayEnd':
                self.in_goal_replay = False
            elif event == 'RoundStarted':
                self.in_goal_replay = False
                self.goal_armed = True
            elif event == 'GoalScored':
                if (self.armed and self.config['show_events'] and self.goal_armed and not self.in_goal_replay
                        and not self.history_replay and not self.result_latched and self.playlist_id in PRIVATE_PLAYLISTS):
                    self.goal_armed = False
                    self.goal_sequence += 1
                    self.goal_until = self.clock()+3
                    scorer = data.get('Scorer') or {}
                    self.goal_team = scorer.get('TeamNum',0) if scorer.get('TeamNum',0) in (0,1) else 0
            if event == 'MatchCreated':
                self.playlist_id = None
                self.history_replay = False
            elif event == 'ReplayCreated':
                self.history_replay = True
                self.gameplay = False
            if event in ('MatchInitialized', 'CountdownBegin', 'RoundStarted', 'MatchStarted'):
                self.gameplay = True
            elif event in ('MatchCreated', 'MatchDestroyed', 'MatchEnded', 'PodiumStart'):
                self.gameplay = False
            elif event == 'UpdateState':
                game = data.get('Game', {})
                if isinstance(game, dict):
                    value = game.get('PlaylistId')
                    if value is not None:
                        self.playlist_id = int(value) if str(value).isdigit() else None
                    if game.get('bHasWinner'):
                        self.gameplay = False
                    elif data.get('Players') and not self.result_latched and not self.history_replay:
                        self.gameplay = True
            if event == 'MatchEnded':
                self.boost_usage.boundary(active=False)
                if self.armed and not self.history_replay and (self.playlist_id is None or self.playlist_id in PRIVATE_PLAYLISTS):
                    self.finish(data.get('WinnerTeamNum'), data.get('MatchGuid'), automatic=True)
                return True
            if event == 'PodiumStart':
                guid = data.get('MatchGuid')
                expected = self.postmatch.get('guid') if self.postmatch else self.match_guid
                if guid and expected and str(guid) != str(expected):
                    return False
                if self.podium_at is None:
                    self.podium_at,self.podium_guid = self.clock(),guid
                if ((self.pending_stats or self.pending_victory) and not self.podium_seen and self.postmatch
                        and (not guid or self.postmatch['guid'] == str(guid))):
                    self.podium_seen = True
                    self.podium_due = self.podium_at + self.config.get('mvp_delay',3)
                return True
            if event == 'MatchStarted':
                self.podium_at = None
                self.podium_guid = None
                self.boost_usage.reset()
                self.roster = []
                self.match_guid = data.get('MatchGuid')
                self.pending_victory = None
                if self.pending_stats:
                    self.stats_cancelled = True
                self.pending_stats = False
                self.podium_due = None
                self.result_latched = False
                self.match_number += 1
                self.manual_live = False
                # Never interrupt the statistics/victory timer at an early kickoff.
                return True
            if event == 'UpdateState' and self.result_latched:
                g = data.get('Game', {})
                teams = g.get('Teams', []) if isinstance(g, dict) else []
                if (data.get('Players') and g.get('TimeSeconds', 0) > 0 and len(teams) == 2
                        and all(t.get('Score') == 0 for t in teams)):
                    self.podium_at = None
                    self.podium_guid = None
                    self.boost_usage.reset()
                    self.roster = []
                    self.match_guid = data.get('MatchGuid')
                    self.pending_victory = None
                    if self.pending_stats:
                        self.stats_cancelled = True
                    self.pending_stats = False
                    self.podium_due = None
                    self.result_latched = False
                    self.match_number += 1
                    self.manual_live = False
            saved = copy.deepcopy(self.postmatch)
            live = copy.deepcopy(self.match) if self.manual_live else None
            try:
                # Studio freezes old results across kickoffs. Do not let that frozen
                # snapshot look like a new kickoff on every zero-score live packet.
                if event == 'UpdateState':
                    self.postmatch = None
                accepted = super().ingest(packet)
            except (ValueError, TypeError, AttributeError, KeyError):
                return False
            finally:
                self.postmatch = saved
                if live is not None:
                    self.match = live
            return accepted

    def finish(self, winner, guid=None, automatic=False):
        with self.lock:
            if winner not in (0, 1):
                return False
            key = str(guid) if guid else f'local-{self.match_number}'
            if self.result_latched or key in self.finished or series_state(self.config)['complete']:
                return False
            self.boost_usage.boundary(active=False)
            self.gameplay = False
            self.finished.add(key)
            self.result_latched = True
            self.stats_cancelled = False
            config = copy.deepcopy(self.config)
            if not automatic or self.config['auto_series']:
                self.config['teams'][winner]['wins'] += 1
            series = series_state(self.config)
            self.config['game'] = series['game']
            wins = [t['wins'] for t in self.config['teams']]
            self.postmatch = dict(guid=key, winner=winner, match=copy.deepcopy(self.match), config=config, wins=wins)
            self.match['banner'] = 'VICTORIA · ' + self.config['teams'][winner]['name']
            self.banner_until = time.monotonic() + 12
            if series['complete'] and not series['tied']:
                leader = 0 if wins[0] > wins[1] else 1
                phase = 'victory' + str(self.animation_order[leader])
                if automatic:
                    self.transition('game')
                    self.pending_victory = phase
                else:
                    self.transition(phase, self.scene_seconds[phase])
            else:
                if automatic and self.stats_enabled:
                    self.transition('game')
                else:
                    self.stats_or_next()
            self.pending_stats = automatic and self.stats_enabled and not self.pending_victory
            self.podium_due = None
            self.podium_seen = False
            if self.podium_at is not None and (not guid or not self.podium_guid or str(guid) == str(self.podium_guid)):
                self.podium_due = self.podium_at + self.config.get('mvp_delay',3)
                self.podium_seen = True
            return True

    def swap_marker_sides(self):
        with self.lock:
            self.config = swap_team_sides(self.config)
            self.animation_order.reverse()

    def reset_series(self):
        with self.lock:
            self.boost_usage.reset()
            self.roster = []
            self.podium_at = None
            self.podium_guid = None
            self.goal_until = 0
            self.goal_armed = True
            self.match_guid = None
            for team in self.config['teams']:
                team['wins'] = 0
            self.config['game'] = 1
            self.postmatch = None
            self.result_latched = False
            self.match_number += 1
            self.match = dict(scores=[0, 0], time=300, overtime=False, players=[], target='', banner='')
            self.transition('game' if self.armed else 'complete')

    def set_marker(self, raw):
        """Normalize imported marker profiles without making a second game connection."""
        updated = normalize_config(raw)
        with self.lock:
            identities = lambda teams: [(t['name'], t['logo']) for t in teams]
            old_ids, new_ids = identities(self.config['teams']), identities(updated['teams'])
            if new_ids == old_ids[::-1] and new_ids != old_ids:
                self.animation_order.reverse()
            for old, new in zip(self.config['teams'], updated['teams']):
                new['short'] = old.get('short', '')
            self.config = updated

    def manual_next(self):
        with self.lock:
            if not self.armed or series_state(self.config)['complete']:
                raise ValueError('Inicia una serie que no haya terminado antes de preparar el siguiente partido.')
            self.boost_usage.reset()
            self.roster = []
            self.podium_at = None
            self.podium_guid = None
            self.goal_until = 0
            self.goal_armed = True
            self.match_guid = None
            self.match_number += 1
            self.result_latched = False
            self.match = dict(scores=[0, 0], time=300, overtime=False, players=[], target='', banner='')
            self.manual_live = True
            self.transition('game')

    def correct(self, scores, seconds, overtime, wins, players, result=False):
        scores, wins = [int(x) for x in scores], [int(x) for x in wins]
        seconds = int(seconds)
        if any(x < 0 for x in scores + wins) or seconds < 0:
            raise ValueError('Los valores no pueden ser negativos.')
        bestof = self.config['bestof']
        if max(wins) > bestof//2+1 or sum(wins) > bestof:
            raise ValueError('Las victorias no son compatibles con el BO.')
        if not isinstance(players, list) or len(players) > 8:
            raise ValueError('La lista de jugadores no es válida.')
        for player in players:
            if not isinstance(player, dict) or player.get('TeamNum') not in (0, 1):
                raise ValueError('Cada jugador necesita TeamNum 0 o 1.')
            for key in ('Score', 'Goals', 'Assists', 'Shots', 'Saves', 'Demolitions'):
                if key in player and (not isinstance(player[key], int) or player[key] < 0):
                    raise ValueError('Las estadísticas deben ser enteros positivos o cero.')
        with self.lock:
            if result and not self.postmatch:
                raise ValueError('Todavía no hay un resultado que corregir.')
            target = self.postmatch['match'] if result else self.match
            target.update(scores=scores, time=seconds, overtime=bool(overtime), players=copy.deepcopy(players))
            for team, count in zip(self.config['teams'], wins):
                team['wins'] = count
            self.config['game'] = series_state(self.config)['game']
            if self.postmatch:
                self.postmatch['wins'] = wins
                if result:
                    self.postmatch['winner'] = 0 if scores[0] > scores[1] else 1 if scores[1] > scores[0] else None
            if not result:
                self.manual_live = True

    def snapshot(self):
        with self.lock:
            state = super().snapshot()
            state['app'] = dict(version='0.8.1',developer='Bruno Reboredo Álvarez')
            state['goal_effect'] = dict(id=self.goal_sequence, remaining=max(0,int((self.goal_until-self.clock())*1000)),team=self.goal_team)
            if state.get('postmatch'):
                state['postmatch']['visible'] = self.phase == 'stats'
            state['studio'] = dict(phase=self.phase, revision=self.revision, gameplay=self.gameplay and not self.history_replay and (self.playlist_id is None or self.playlist_id in PRIVATE_PLAYLISTS),
                                   remaining=max(0, self.deadline-self.clock()) if self.deadline is not None else None,
                                   held=self.paused is not None, manual=self.manual_live,
                                   field_opening_elapsed=self.field_opening_elapsed,
                                   waiting_podium=bool(self.pending_stats or self.pending_victory) and self.podium_due is None,
                                   pending_victory=self.pending_victory,
                                   podium_remaining=max(0, self.podium_due-self.clock()) if self.podium_due is not None else None)
            if (self.goal_until > self.clock() and self.config['show_events'] and self.phase == 'game'
                    and not self.history_replay and (self.playlist_id is None or self.playlist_id in PRIVATE_PLAYLISTS)):
                state['studio']['gameplay'] = True
            state['overlay_visible'] = bool(state['studio']['gameplay'] and self.phase == 'game')
            return state
