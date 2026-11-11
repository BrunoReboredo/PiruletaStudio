import copy
import unittest
from studio import Studio
from vendor.postmatch.boost_usage import BoostUsage


class StatisticsUpdateTests(unittest.TestCase):
    def test_boost_usage_drops_pickups_demolition_missing_and_replays(self):
        usage = BoostUsage()
        def sample(boost, **extra):
            player = {'Name': 'Piru', 'TeamNum': 0, 'Boost': boost, 'bBoosting': True, **extra}
            usage.update([player])
            return player['BoostUsed']
        self.assertEqual(sample(80), 0)
        self.assertEqual(sample(65), 15)
        self.assertEqual(sample(100), 15)
        self.assertEqual(sample(90), 25)
        self.assertEqual(sample(0, bDemolished=True), 25)
        self.assertEqual(sample(33), 25)
        self.assertEqual(sample(None), 25)
        self.assertEqual(sample(0), 25)
        usage.boundary(active=False)
        self.assertEqual(sample(100), 25)
        usage.boundary()
        self.assertEqual(sample(33), 25)
        self.assertEqual(sample(20), 38)
        usage.update([], replay=True)
        self.assertEqual(sample(0), 38)
        usage.reset()
        self.assertEqual(sample(33), 0)

    def test_boost_usage_per_player_freezes_and_resets_for_new_match(self):
        store = Studio()
        store.armed = True
        def tick(a, b, guid='one'):
            store.ingest({'Event': 'UpdateState', 'Data': {'MatchGuid': guid,
                'Game': {'TimeSeconds': 100, 'Teams': [{'TeamNum': 0, 'Score': 1}]},
                'Players': [{'Name': name, 'TeamNum': 0, 'Boost': boost, 'bBoosting': True}
                            for name, boost in [('A', a), ('B', b)]]}})
        tick(70, 50)
        tick(50, 40)
        store.ingest({'Event': 'GoalScored', 'Data': {}})
        tick(0, 0)
        store.ingest({'Event': 'RoundStarted', 'Data': {}})
        tick(33, 33)
        tick(23, 13)
        store.ingest({'Event': 'MatchEnded', 'Data': {'WinnerTeamNum': 0, 'MatchGuid': 'one'}})
        self.assertEqual([p['BoostUsed'] for p in store.postmatch['match']['players']], [30, 30])
        tick(0, 0)
        self.assertEqual([p['BoostUsed'] for p in store.postmatch['match']['players']], [30, 30])
        tick(33, 33, guid='two')
        self.assertEqual([p['BoostUsed'] for p in store.postmatch['match']['players']], [30, 30])
        self.assertEqual([p['BoostUsed'] for p in store.match['players']], [0, 0])

    def test_zero_score_next_match_keeps_accumulating_without_erasing_old_result(self):
        store = Studio()
        store.armed = True
        def tick(boost, guid):
            store.ingest(dict(Event='UpdateState', Data=dict(MatchGuid=guid,
                Game=dict(TimeSeconds=200, Teams=[dict(TeamNum=0, Score=0), dict(TeamNum=1, Score=0)]),
                Players=[dict(Name='A', TeamNum=0, Boost=boost, bBoosting=True)])))
        tick(100, 'first')
        tick(80, 'first')
        store.ingest(dict(Event='MatchEnded', Data=dict(WinnerTeamNum=0, MatchGuid='first')))
        result = copy.deepcopy(store.postmatch)
        tick(100, 'second')
        tick(90, 'second')
        tick(75, 'second')
        self.assertEqual(store.match['players'][0]['BoostUsed'], 25)
        self.assertEqual(store.postmatch, result)
        store.ingest(dict(Event='MatchStarted', Data=dict(MatchGuid='third')))
        tick(33, 'third')
        self.assertEqual(store.match['players'][0]['BoostUsed'], 0)

    def test_pause_and_replay_do_not_add_consumption_or_cross_boundaries(self):
        store = Studio()
        def event(name):
            store.ingest(dict(Event=name, Data={}))
        def tick(boost, replay=False):
            store.ingest(dict(Event='UpdateState', Data=dict(MatchGuid='one',
                Game=dict(TimeSeconds=100, bReplay=replay),
                Players=[dict(Name='A', TeamNum=0, Boost=boost, bBoosting=True)])))
        tick(100)
        tick(80)
        event('MatchPaused')
        tick(0)
        event('MatchUnpaused')
        tick(33)
        tick(23)
        event('GoalReplayStart')
        tick(0, replay=True)
        event('GoalReplayEnd')
        tick(100)
        event('RoundStarted')
        tick(33)
        tick(23)
        self.assertEqual(store.match['players'][0]['BoostUsed'], 40)

    def test_manual_reset_clears_accumulator(self):
        store = Studio()
        store.boost_usage.totals['player'] = 500
        store.reset_series()
        self.assertFalse(store.boost_usage.totals)

    def test_partial_packets_and_shared_primary_id_keep_every_player(self):
        store=Studio()
        store.armed=True
        def tick(players):
            store.ingest(dict(Event='UpdateState',Data=dict(MatchGuid='one',Game=dict(TimeSeconds=100),Players=players)))
        players=[dict(Name=n,PrimaryId='shared',TeamNum=t,Boost=100,bBoosting=True,Score=i*100) for i,(n,t) in enumerate([('A',0),('B',0),('C',0),('D',1),('E',1),('F',1)])]
        tick(players)
        tick([dict(players[0],Boost=80),dict(players[3],Boost=70)])
        self.assertEqual(len(store.match['players']),6)
        totals={p['Name']:p['BoostUsed'] for p in store.match['players']}
        self.assertEqual(totals['A'],20)
        self.assertEqual(totals['D'],30)
        self.assertEqual(totals['B'],0)
        store.ingest(dict(Event='MatchEnded',Data=dict(WinnerTeamNum=0,MatchGuid='one')))
        self.assertEqual(len(store.postmatch['match']['players']),6)

    def test_omitted_blue_team_and_duplicate_initialization_preserve_roster(self):
        store=Studio()
        def tick(players):
            store.ingest(dict(Event='UpdateState',Data=dict(MatchGuid='one',Game={},Players=players)))
        tick([dict(Name='Blue',Boost=100,bBoosting=True)])
        store.ingest(dict(Event='MatchInitialized',Data=dict(MatchGuid='one')))
        tick([dict(Name='Orange',TeamNum=1,Boost=100,bBoosting=True)])
        self.assertEqual({p['Name']:p['TeamNum'] for p in store.match['players']},{'Blue':0,'Orange':1})
