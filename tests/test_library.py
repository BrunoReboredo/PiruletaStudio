import copy
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from library import Library, clip_keys
from render import prepare
from studio import defaults, validate
from test_features import mp4


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root/'biblioteca')
        self.profile = defaults()
        logo = self.root/'logo.png'
        shutil.copyfile(Path(__file__).resolve().parents[1]/'vendor/overlay/assets/torneo.png', logo)
        for i, team in enumerate(self.profile['teams']):
            team.update(name='Team '+str(i), short='T'+str(i), logo=str(logo))
        executable = self.root/'blender.exe'
        executable.write_bytes(b'fixture')
        self.profile['blender'] = str(executable)
        self.signature = patch('render.renderer_signature', return_value='template-v1')
        self.signature.start()
        self.addCleanup(self.signature.stop)
        def renderer(blender, config, folder, cancelled):
            scene = config['only_scenes'][0]
            (folder/(scene+'.mp4')).write_bytes(mp4(13 if scene == 'Prepartido' else 2))
        self.runner_patch = patch('render.run_job', side_effect=renderer)
        self.runner = self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)

    def prepare(self, profile=None):
        return prepare(profile or self.profile, self.root/'renders', lambda msg: None,
                       threading.Event(), library_dir=self.library.root)

    def test_assets_deduplicate_by_content_and_survive_original_removal(self):
        self.profile['teams'][0].update(skin=self.profile['teams'][0]['logo'], skin_confirmed='Octane')
        saved = self.library.import_profile(validate(self.profile))
        renamed = self.root/'renamed.png'
        shutil.copyfile(self.profile['teams'][0]['logo'], renamed)
        self.assertEqual(self.library.store_asset(renamed, 'logos'), saved['teams'][0]['logo'])
        self.assertEqual(len(list((self.library.root/'logos').iterdir())), 1)
        self.assertEqual(len(list((self.library.root/'calcomanias').iterdir())), 1)
        Path(self.profile['teams'][0]['logo']).unlink()
        renamed.unlink()
        validate(saved)

    def test_filename_model_detection_survives_storage(self):
        skin = self.root/'Octane.png'
        shutil.copyfile(self.profile['teams'][0]['logo'], skin)
        self.profile['teams'][0]['skin'] = str(skin)
        saved = self.library.import_profile(validate(self.profile))
        self.assertEqual(saved['teams'][0]['skin_confirmed'], 'Octane')
        validate(saved)

    def test_second_request_renders_nothing_even_with_different_file_names(self):
        first = self.prepare()
        self.assertEqual(self.runner.call_count, 3)
        other = copy.deepcopy(self.profile)
        renamed = self.root/'another-logo.png'
        shutil.copyfile(other['teams'][0]['logo'], renamed)
        for team in other['teams']:
            team['logo'] = str(renamed)
        self.runner.reset_mock()
        second = self.prepare(other)
        self.runner.assert_not_called()
        self.assertEqual(set(second['reused']), {'pre', 'victory0', 'victory1'})
        self.assertNotEqual(first['files']['pre'], second['files']['pre'])

    def test_only_changed_team_and_pre_match_are_regenerated(self):
        self.prepare()
        changed = copy.deepcopy(self.profile)
        changed['teams'][0]['color'] = '#123456'
        self.runner.reset_mock()
        result = self.prepare(changed)
        self.assertEqual(self.runner.call_count, 2)
        self.assertEqual(result['reused'], ['victory1'])

    def test_team_swap_reuses_both_victories(self):
        self.prepare()
        swapped = copy.deepcopy(self.profile)
        swapped['teams'].reverse()
        self.runner.reset_mock()
        result = self.prepare(swapped)
        self.assertEqual(self.runner.call_count, 1)
        self.assertEqual(set(result['reused']), {'victory0', 'victory1'})

    def test_engine_changes_do_not_reuse_different_quality(self):
        self.prepare()
        cycles = copy.deepcopy(self.profile)
        cycles['render_engine'] = 'CYCLES'
        self.runner.reset_mock()
        result = self.prepare(cycles)
        self.assertEqual(self.runner.call_count, 3)
        self.assertEqual(result['reused'], [])
        self.assertTrue(all(call.args[1]['engine'] == 'CYCLES' for call in self.runner.call_args_list))

    def test_corrupt_cached_video_is_regenerated(self):
        self.prepare()
        key = clip_keys(self.profile, 'template-v1')['victory0']
        (self.library.root/'videos'/key/'video.mp4').write_bytes(b'broken')
        self.runner.reset_mock()
        result = self.prepare()
        self.assertEqual(self.runner.call_count, 1)
        self.assertEqual(set(result['reused']), {'pre', 'victory1'})

    def test_full_cache_does_not_require_installed_blender(self):
        self.prepare()
        self.profile['blender'] = str(self.root/'missing-blender.exe')
        self.runner.reset_mock()
        result = self.prepare()
        self.runner.assert_not_called()
        self.assertEqual(len(result['reused']), 3)

    def test_template_change_invalidates_videos(self):
        self.prepare()
        self.runner.reset_mock()
        with patch('render.renderer_signature', return_value='template-v2'):
            self.prepare()
        self.assertEqual(self.runner.call_count, 3)

    def test_series_length_and_round_do_not_force_visual_renders(self):
        self.prepare()
        self.profile.update(bestof=7, round='Semifinal')
        self.runner.reset_mock()
        self.assertEqual(len(self.prepare()['reused']), 3)
        self.runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
