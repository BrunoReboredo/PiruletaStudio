import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from studio import Studio, defaults
from vendor.overlay.app import normalize_config
from vendor.postmatch.data_sources import read_source, auto_mapping
from vendor.postmatch.prematch import source_signature


class PrematchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.store = Studio(clock=lambda: self.now)
        self.profile = defaults()
        self.logo = Path(__file__).resolve().parents[1]/'vendor/overlay/assets/torneo.png'
        for i, team in enumerate(self.profile['teams']):
            team.update(name='Club '+str(i), short='C'+str(i), logo=str(self.logo))
        self.store.configure(self.profile)
        self.store.config = normalize_config({**self.store.config, 'pre_metrics': ['Shots', 'Goals'],
            'database': dict(provider='SQLite', location='test.db', query='SELECT * FROM stats',
                             team_names=['Alpha', 'Beta'], event='Liga', round='Final')})
        self.dataset = dict(headers=['Team', 'Shots', 'Goals', 'Logo'], rows=[
            dict(Team='Alpha', Shots=10, Goals=3, Logo=self.logo.read_bytes()),
            dict(Team='Beta', Shots=8, Goals=2, Logo=self.logo.read_bytes())])
        self.store.config['database']['mapping'] = auto_mapping(self.dataset['headers'])
        self.store.prematch_data = self.dataset
        self.store.prematch_source = source_signature(self.store.config['database'])

    def test_waits_for_choice_then_never_reappears_during_series(self):
        self.store.begin_prematch()
        self.assertEqual(self.store.phase, 'prematch')
        self.assertTrue(self.store.snapshot()['prematch']['visible'])
        self.now = 300
        self.store.ingest(dict(Event='MatchStarted', Data={}))
        self.store.tick()
        self.assertEqual(self.store.phase, 'prematch')
        self.store.start('field')
        self.assertIsNone(self.store.snapshot()['prematch'])
        self.now += 16
        self.store.tick()
        self.store.try_prematch()
        self.store.begin_prematch()
        self.assertEqual(self.store.phase, 'game')
        self.assertTrue(self.store.prematch_consumed)

    def test_late_source_and_new_series_with_independent_teams(self):
        self.store.prematch_data = None
        self.store.begin_prematch()
        self.assertEqual(self.store.phase, 'complete')
        self.store.prematch_data = self.dataset
        self.store.try_prematch()
        result = self.store.snapshot()['prematch']
        self.assertEqual(result['config']['teams'][0]['name'], 'Alpha')
        self.assertEqual(self.store.config['teams'][0]['name'], 'Club 0')
        self.assertTrue(result['config']['teams'][0]['logo'].startswith('/prematch-logo/'))
        self.assertTrue(self.store.prematch_logos)
        self.store.start()
        self.store.configure(self.profile)
        self.store.begin_prematch()
        self.assertEqual(self.store.phase, 'prematch')

    def test_changed_source_cannot_reuse_stale_data(self):
        self.store.begin_prematch()
        self.store.config['database']['location'] = 'another.db'
        self.store.try_prematch()
        self.assertIsNone(self.store.snapshot()['prematch'])
        self.assertEqual(self.store.phase, 'complete')

    def test_sqlite_source_read_only_and_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'stats.db'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE stats (Team TEXT, Shots INTEGER)')
                conn.executemany('INSERT INTO stats VALUES (?, ?)', [('Alpha', 10), ('Beta', 8)])
            conn.close()
            config = dict(self.store.config['database'], location=str(path))
            table = read_source(config)
            self.assertEqual(len(table['rows']), 2)
            self.assertEqual(auto_mapping(table['headers'])['Team'], 'Team')
            config['query'] = 'DELETE FROM stats'
            with self.assertRaises(ValueError):
                read_source(config)

    def test_actions_expire_and_clear_during_replay(self):
        self.store.start()
        self.store.transition('game')
        self.store.playlist_id = 6
        player = dict(Name='Piru', TeamNum=0, Shortcut=1)
        self.store.ingest(dict(Event='StatfeedEvent', Data=dict(EventName='ShotOnGoal', MainTarget=player)))
        self.assertEqual(self.store.snapshot()['player_actions'][0]['kind'], 'shot')
        self.now = 4.6
        self.assertEqual(self.store.snapshot()['player_actions'], [])
        self.store.ingest(dict(Event='StatfeedEvent', Data=dict(EventName='EpicSave', MainTarget=player)))
        self.assertEqual(self.store.snapshot()['player_actions'][0]['kind'], 'save')
        self.store.ingest(dict(Event='GoalReplayStart', Data={}))
        self.assertEqual(self.store.snapshot()['player_actions'], [])
        self.store.ingest(dict(Event='StatfeedEvent', Data=dict(EventName='Assist', MainTarget=player)))
        self.assertEqual(self.store.snapshot()['player_actions'], [])
