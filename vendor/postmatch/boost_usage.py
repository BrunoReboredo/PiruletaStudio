"""Conservative boost-use estimate from consecutive live spectator samples."""
import math
from .roster import player_key


class BoostUsage:
    def __init__(self):
        self.reset()

    def reset(self):
        self.totals = {}
        self.previous = {}
        self.active = True

    def boundary(self, active=True):
        self.previous.clear()
        self.active = active

    def update(self, players, replay=False):
        if replay or not self.active:
            self.previous.clear()
            for player in players:
                key = player_key(player)
                player['BoostUsed'] = self.totals.get(key)
            return
        current = {}
        for player in players:
            key = player_key(player)
            boost = player.get('Boost')
            valid = isinstance(boost, (int, float)) and math.isfinite(boost) and 0 <= boost <= 100
            valid = valid and not player.get('bDemolished', False) and player.get('bHasCar', True)
            if valid:
                self.totals.setdefault(key, 0)
                prior = self.previous.get(key)
                if prior is not None and (prior[1] or player.get('bBoosting', False)):
                    self.totals[key] += max(0, prior[0] - boost)
                current[key] = (boost, player.get('bBoosting', False))
            player['BoostUsed'] = round(self.totals[key]) if key in self.totals else None
        self.previous = current
