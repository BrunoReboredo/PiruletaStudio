import copy
import json
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from media import mp4_duration, imported_manifest
from studio import Studio, defaults
from library import clip_keys
from render import renderer_signature


def box(kind, content):
    return struct.pack('>I4s', len(content)+8, kind)+content


def mp4(seconds, codec=b'avc1'):
    mvhd = b'\0'*12+struct.pack('>II', 1000, int(seconds*1000))
    stsd = b'\0'*4+struct.pack('>I', 1)+box(codec, b'\0'*20)
    hdlr = b'\0'*8+b'vide'+b'\0'*12
    mdia = box(b'hdlr', hdlr)+box(b'minf', box(b'stbl', box(b'stsd', stsd)))
    return box(b'ftyp', b'isom\0\0\0\0isomavc1')+box(b'moov', box(b'mvhd', mvhd)+box(b'trak', box(b'mdia', mdia)))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.store = Studio(clock=lambda: self.now)
        self.store.armed = True

    def end_auto(self, bestof=3):
        self.store.config['bestof'] = bestof
        self.store.ingest(dict(Event='MatchEnded', Data=dict(WinnerTeamNum=0, MatchGuid='result')))

    def podium(self, guid='result'):
        self.store.ingest(dict(Event='PodiumStart', Data=dict(MatchGuid=guid)))

    def test_waits_for_podium_then_three_seconds_and_ignores_duplicates(self):
        self.end_auto()
        self.now = 40
        self.store.tick()
        self.assertEqual(self.store.phase, 'game')
        self.podium('old-match')
        self.assertIsNone(self.store.podium_due)
        self.podium()
        self.now = 42.9
        self.podium()
        self.store.tick()
        self.assertEqual(self.store.phase, 'game')
        self.now = 43
        self.store.tick()
        self.assertEqual(self.store.phase, 'stats')
        self.assertEqual(self.store.deadline, 53)

    def test_victory_waits_for_later_podium(self):
        self.end_auto(bestof=1)
        self.now = 4
        self.store.tick()
        self.assertEqual(self.store.phase, 'game')
        self.podium()
        self.now = 7
        self.store.tick()
        self.assertEqual(self.store.phase, 'stats')

    def test_early_podium_never_interrupts_victory(self):
        self.end_auto(bestof=1)
        self.podium()
        self.now = 3
        self.store.tick()
        self.assertEqual(self.store.phase, 'victory0')
        self.now = 4
        self.store.tick()
        self.assertEqual(self.store.phase, 'stats')

    def test_manual_show_hide_reset_and_new_match_cancel_pending_stats(self):
        for action in (lambda: self.store.show_stats(), self.store.hide_stats,
                       self.store.reset_series,
                       lambda: self.store.ingest(dict(Event='MatchStarted', Data={}))):
            self.store.reset_series()
            self.end_auto()
            self.podium()
            action()
            self.assertFalse(self.store.pending_stats)
            self.now += 5
            self.store.tick()
        self.assertEqual(self.store.phase, 'game')

    def test_new_kickoff_packet_cancels_old_podium_wait(self):
        self.end_auto()
        self.podium()
        self.store.ingest(dict(Event='UpdateState', Data=dict(
            Game=dict(TimeSeconds=300, Teams=[dict(Score=0, TeamNum=0), dict(Score=0, TeamNum=1)]),
            Players=[dict(Name='New game', TeamNum=0)])))
        self.now = 5
        self.store.tick()
        self.assertFalse(self.store.pending_stats)
        self.assertEqual(self.store.phase, 'game')

    def test_hide_pending_final_stats_keeps_victory_and_finishes_series(self):
        self.end_auto(bestof=1)
        self.podium()
        self.store.hide_stats()
        self.assertEqual(self.store.phase, 'victory0')
        self.now = 4
        self.store.tick()
        self.assertEqual(self.store.phase, 'complete')

    def test_disable_auto_while_waiting_does_not_leave_final_series_in_game(self):
        self.end_auto(bestof=1)
        self.now = 4
        self.store.tick()
        self.store.stats_enabled = False
        self.store.tick()
        self.assertEqual(self.store.phase, 'complete')

    def test_marker_only_in_game_preserves_pause_and_replay(self):
        s = self.store
        self.assertFalse(s.snapshot()['studio']['gameplay'])
        for event in ('MatchInitialized', 'CountdownBegin', 'RoundStarted'):
            s.ingest(dict(Event=event, Data={}))
            self.assertTrue(s.gameplay)
        for event in ('MatchPaused', 'GoalReplayStart', 'GoalReplayEnd', 'MatchUnpaused'):
            s.ingest(dict(Event=event, Data={}))
            self.assertTrue(s.gameplay)
        self.end_auto()
        self.assertFalse(s.gameplay)
        self.podium()
        self.assertFalse(s.gameplay)
        s.ingest(dict(Event='MatchDestroyed', Data={}))
        self.assertFalse(s.gameplay)

    def test_swapped_team_plays_its_original_prepared_victory(self):
        s = self.store
        s.config['bestof'] = 1
        original = s.config['teams'][0]['name']
        s.swap_marker_sides()
        self.assertEqual(s.config['teams'][1]['name'], original)
        s.finish(1)
        self.assertEqual(s.phase, 'victory0')

    def test_imported_victory_duration_precedes_ten_second_stats(self):
        s = self.store
        s.config['bestof'] = 1
        s.scene_seconds = dict(pre=20, victory0=7.5, victory1=9)
        s.finish(0)
        self.now = 7.4
        s.tick()
        self.assertEqual(s.phase, 'victory0')
        self.now = 7.5
        s.tick()
        self.assertEqual(s.phase, 'stats')
        self.assertEqual(s.deadline, 17.5)
        self.now = 17.5
        s.tick()
        self.assertEqual(s.phase, 'complete')

    def test_manual_stats_can_be_kept_and_hidden_without_editing_result(self):
        s = self.store
        s.finish(0)
        result = copy.deepcopy(s.postmatch)
        s.show_stats()
        self.now = 100
        s.tick()
        self.assertEqual(s.phase, 'stats')
        self.assertIsNone(s.deadline)
        s.hide_stats()
        self.assertEqual(s.phase, 'game')
        self.assertEqual(s.postmatch, result)

    def test_hide_stats_does_not_cut_victory(self):
        self.store.config['bestof'] = 1
        self.store.finish(0)
        self.store.hide_stats()
        self.assertEqual(self.store.phase, 'victory0')

    def test_optional_stats_off_keeps_victory(self):
        s = self.store
        s.stats_enabled = False
        s.config['bestof'] = 1
        s.finish(0)
        self.assertEqual(s.phase, 'victory0')
        self.now = 4
        s.tick()
        self.assertEqual(s.phase, 'complete')

    def test_disabling_api_wins_still_allows_manual_wins(self):
        s = self.store
        s.config['auto_series'] = False
        s.ingest(dict(Event='MatchEnded', Data=dict(WinnerTeamNum=0, MatchGuid='api')))
        self.assertEqual(s.config['teams'][0]['wins'], 0)
        s.manual_next()
        s.finish(0)
        self.assertEqual(s.config['teams'][0]['wins'], 1)

    def test_reset_preserves_design_and_clears_old_result(self):
        s = self.store
        s.config.update(opacity=73, custom_css='.name{color:red}')
        s.finish(0, 'old')
        s.reset_series()
        self.assertEqual(s.config['opacity'], 73)
        self.assertIsNone(s.postmatch)
        self.assertEqual(s.config['teams'][0]['wins'], 0)
        self.assertFalse(s.finish(0, 'old'))


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, seconds, codec=b'avc1'):
        path = self.root/name
        path.write_bytes(mp4(seconds, codec))
        return path

    def test_read_duration_without_blender(self):
        self.assertEqual(mp4_duration(self.write('video.mp4', 7.25)), 7.25)

    def test_reject_invalid_and_unsupported_videos(self):
        for name, seconds, codec in (('bad.mp4', 0, b'avc1'), ('hevc.mp4', 8, b'hvc1'), ('text.txt', 8, b'avc1')):
            with self.assertRaises(ValueError):
                mp4_duration(self.write(name, seconds, codec))
        broken = self.root/'broken.mp4'
        broken.write_bytes(b'not a video')
        with self.assertRaises(ValueError):
            mp4_duration(broken)

    def test_manual_manifest_requires_all_three_and_tracks_durations(self):
        files = {k: str(self.write(k+'.mp4', seconds)) for k,seconds in [('pre', 13), ('victory0', 6), ('victory1', 8)]}
        manifest = imported_manifest('teams', files)
        self.assertEqual(manifest['source'], 'manual')
        self.assertEqual(manifest['durations'], dict(pre=13, victory0=6, victory1=8))
        with self.assertRaises(ValueError):
            imported_manifest('teams', {'pre': files['pre']})


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mock_connection = patch('app.GameConnection', autospec=True)
        self.connection = self.mock_connection.start()
        self.addCleanup(self.mock_connection.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, library_dir=Path(self.temp.name)/'biblioteca')
        self.addCleanup(self.app.close)
        p = defaults()
        logo = Path(__file__).resolve().parents[1]/'vendor/overlay/assets/torneo.png'
        for i, team in enumerate(p['teams']):
            team.update(name=f'Team {i}', short=f'T{i}', logo=str(logo))
        self.app.populate(p)
        self.app.configure()

    def test_marker_options_update_the_shared_output(self):
        marker = self.app.marker
        marker.vars['font'].set('Impact')
        marker.vars['scale'].set('120')
        marker.vars['show_players'].set(False)
        marker.panel_color_vars['boost'].set('Equipo A')
        marker.panel_vars['boost'][0].set('1500')
        marker.css.insert('1.0', '.name {color:red}')
        self.assertTrue(marker.apply())
        config = self.app.store.snapshot()['config']
        self.assertEqual(config['font'], 'Impact')
        self.assertFalse(config['show_players'])
        self.assertEqual(config['panel_colors']['boost'], 'pink')
        self.assertEqual(config['panels']['boost'][0], 1500)
        self.assertIn('color:red', config['custom_css'])
        self.assertEqual(config['teams'][0]['short'], 'T0')
        self.connection.assert_called_once()
        self.connection.return_value.connect.assert_called_once()

    def test_completed_series_returns_to_empty_setup_once(self):
        app = self.app
        app.store.config['bestof'] = 1
        app.store.armed = True
        app.store.finish(0)
        app.store.transition('complete')
        app.tick()
        self.assertEqual(app.tabs.select(), str(app.setup_tab))
        self.assertIsNone(app.profile)
        self.assertFalse(app.store.armed)
        self.assertEqual(str(app.start_button['state']), 'disabled')
        self.assertEqual(app.store.config['teams'][0]['wins'], 1)
        for fields in app.fields:
            self.assertTrue(all(not v.get() for v in fields.values()))
        app.fields[0]['name'].set('Siguiente equipo')
        app.tick()
        self.assertEqual(app.fields[0]['name'].get(), 'Siguiente equipo')
        self.assertIn('finalizada', app.note.get())

    def test_marker_visibility_uses_check_images(self):
        self.assertEqual(len(self.root.marker_check_images), 2)
        self.assertEqual(self.root.marker_check_images[1].get(7, 12), (255, 255, 255))
        def checks(widget):
            return [child for child in widget.winfo_children() if child.winfo_class() == 'TCheckbutton'] + [c for child in widget.winfo_children() for c in checks(child)]
        checkboxes = checks(self.app.marker.design_tabs)
        self.assertTrue(checkboxes)
        self.assertTrue(all(c['style'] == 'Marker.TCheckbutton' for c in checkboxes))

    def test_marker_color_picker_preserves_animation_profile(self):
        profile = copy.deepcopy(self.app.profile)
        before = clip_keys(profile, renderer_signature())
        with patch('vendor.overlay.app.colorchooser.askcolor', return_value=((0, 255, 0), '#00ff00')):
            self.app.marker.color('pink')
        self.assertEqual(self.app.store.config['colors']['pink'], '#00ff00')
        self.assertEqual(self.app.profile, profile)
        self.assertEqual(clip_keys(self.app.profile, renderer_signature()), before)

    def test_user_videos_enable_start_and_use_their_duration(self):
        for key, seconds in [('pre', 22), ('victory0', 6), ('victory1', 8)]:
            path = Path(self.temp.name)/(key+'.mp4')
            path.write_bytes(mp4(seconds))
            self.app.video_fields[key].set(str(path))
        with patch('app.prepare') as blender:
            self.app.use_manual_videos()
            blender.assert_not_called()
        self.assertEqual(str(self.app.start_button.cget('state')), 'normal')
        self.app.start()
        self.assertEqual(self.app.store.phase, 'pre')
        self.assertEqual(self.app.store.scene_seconds['pre'], 22)

    def test_stats_controls_leave_result_read_only(self):
        self.app.store.finish(0)
        result = copy.deepcopy(self.app.store.postmatch)
        self.app.show_statistics(False)
        self.assertEqual(self.app.store.phase, 'stats')
        self.assertIsNone(self.app.store.deadline)
        self.app.store.hide_stats()
        self.assertEqual(self.app.store.postmatch, result)
        self.assertFalse(hasattr(self.app, 'player_rows'))

    def test_same_series_recovers_all_videos_without_rendering(self):
        keys = clip_keys(self.app.profile, renderer_signature())
        for key, duration in [('pre', 13), ('victory0', 2), ('victory1', 2)]:
            video = Path(self.temp.name)/(key+'.mp4')
            video.write_bytes(mp4(duration))
            self.app.library.save_clip(keys[key], video, dict(engine='EEVEE', kind=key))
        with patch('app.prepare') as renderer:
            self.app.configure()
            renderer.assert_not_called()
        self.assertEqual(str(self.app.start_button.cget('state')), 'normal')
        self.assertEqual(self.app.media['source'], 'library')
        self.app.start()
        self.assertEqual(self.app.store.phase, 'pre')
        self.assertEqual(self.app.store.scene_seconds['pre'], 13)


if __name__ == '__main__':
    unittest.main()
