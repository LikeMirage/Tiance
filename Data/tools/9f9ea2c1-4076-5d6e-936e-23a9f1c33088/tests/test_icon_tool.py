from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'program'))
from catalog import Catalog
from main import run
from rendering import rasterize, styled_svg, wrap_label

IDS = ['phosphor:regular/gear', 'phosphor:duotone/gear-duotone',
       'lucide:factory', 'tabler:outline/network', 'heroicons:24/outline/cog-8-tooth']


class IconToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tiance-icon-test-')
        self.folder = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'TIANCE_WORKSPACE_ROOT': str(self.folder)})
        self.environment.start()
        self.network = patch.object(socket, 'create_connection', side_effect=AssertionError('Tool attempted network access'))
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.environment.stop()
        self.temp.cleanup()

    def test_complete_pinned_archives_and_index(self):
        expected = {'phosphor': 9072, 'lucide': 2322, 'tabler': 6257, 'heroicons': 1288}
        records = self.catalog.records
        self.assertEqual(len(records), 18939)
        for key, count in expected.items():
            library = self.catalog.libraries[key]
            path = self.catalog.assets / library['archive']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), library['archive_sha256'])
            entries = [r for r in records if r['library'] == key]
            self.assertEqual(len(entries), count)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {r['path'] for r in entries})
                for record in entries:
                    raw = archive.read(record['path'])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
                    self.assertEqual(ET.fromstring(raw).tag, '{http://www.w3.org/2000/svg}svg')

    def test_cross_library_search_and_real_pagination(self):
        first = run({'action': 'search', 'queries': ['gear', 'factory'], 'limit': 2})
        self.assertTrue(first['ok'], first)
        page = first['data']['queries'][0]
        self.assertGreater(page['total'], 2)
        self.assertEqual(len(first['data']['queries']), 2)
        second = run({'action': 'search', 'queries': ['gear'], 'limit': 2, 'offset': page['next_offset']})
        self.assertFalse({r['id'] for r in page['items']} & {r['id'] for r in second['data']['queries'][0]['items']})
        all_matches = run({'action': 'search', 'queries': ['circle'], 'limit': 10000})
        data = all_matches['data']['queries'][0]
        self.assertEqual(data['total'], data['returned'])
        self.assertEqual({r['library'] for r in data['items']}, set(self.catalog.libraries))
        filtered = run({'action': 'search', 'queries': ['gear'], 'libraries': ['phosphor']})
        self.assertEqual({r['library'] for r in filtered['data']['queries'][0]['items']}, {'phosphor'})
        self.assertFalse(list(self.folder.iterdir()), 'Search must not create preview files')

    def test_exact_name_is_ranked_first_case_insensitive(self):
        result = run({'action': 'search', 'queries': ['FACTORY'], 'libraries': ['lucide']})
        self.assertEqual(result['data']['queries'][0]['items'][0]['id'], 'lucide:factory')

    def test_metadata_tags_are_searchable(self):
        # "cog" is a real Phosphor gear tag, not an icon called "cog".
        result = run({'action': 'search', 'queries': ['cog'], 'libraries': ['phosphor'], 'limit': 1000})
        self.assertIn('phosphor:regular/gear', [r['id'] for r in result['data']['queries'][0]['items']])
        # Numeric tags in the original Tabler metadata must remain searchable.
        result = run({'action': 'search', 'queries': ['420'], 'libraries': ['tabler']})
        self.assertTrue(result['ok'], result)
        self.assertIn('tabler:filled/bong', [r['id'] for r in result['data']['queries'][0]['items']])

    def test_unknown_library_and_ids_fail_without_writing(self):
        for payload in ({'action': 'search', 'queries': ['x'], 'libraries': ['missing']},
                        {'action': 'export', 'icons': IDS + ['lucide:../../../escape']},
                        {'action': 'preview', 'icons': IDS + ['missing:id']}):
            with self.subTest(payload=payload):
                self.assertFalse(run(payload)['ok'])
        self.assertFalse(list(self.folder.iterdir()))

    def test_bad_and_irrelevant_parameters_rejected(self):
        for payload in ({'action': 'search', 'queries': []}, {'action': 'preview'},
                        {'action': 'libraries', 'output_dir': str(self.folder)},
                        {'action': 'search', 'queries': ['gear'], 'size': 10},
                        {'action': 'export', 'icons': IDS, 'size': True},
                        {'action': 'export', 'icons': IDS, 'formats': ['jpeg']},
                        {'action': 'preview', 'icons': IDS, 'columns': 0},
                        {'action': 'preview', 'icons': IDS, 'color': 'red'},
                        {'action': 'preview', 'icons': [IDS[0], IDS[0]]}):
            with self.subTest(payload=payload):
                self.assertFalse(run(payload)['ok'])

    def test_preview_numbering_and_labels_are_complete(self):
        from PIL import Image, ImageFont
        result = run({'action': 'preview', 'icons': IDS, 'columns': 3, 'color': '#FFFFFF'})
        self.assertTrue(result['ok'], result)
        data = result['data']
        self.assertEqual([r['id'] for r in data['items']], IDS)
        self.assertEqual([r['number'] for r in data['items']], list(range(1, len(IDS) + 1)))
        self.assertEqual(data['items'][-1]['row'], 2)
        with Image.open(data['preview']['path']) as image:
            self.assertEqual(image.width, 3 * 248)
            self.assertGreater(image.height, 2 * 200)
            self.assertGreater(len(image.getcolors(image.width * image.height)), 10)
        manifest = json.loads(Path(data['manifest']['path']).read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['libraries']), 4)
        self.assertEqual(len(data['license_files']), 4)
        label = 'phosphor:duotone/a-very-long-name-that-must-not-disappear-duotone'
        self.assertEqual(''.join(wrap_label(label, ImageFont.load_default(size=14), 150)), label)

    def test_preview_more_than_twenty_candidates_is_not_truncated(self):
        ids = [r['id'] for r in self.catalog.records[:26]]
        result = run({'action': 'preview', 'icons': ids})
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['data']['items']), 26)
        self.assertEqual(result['data']['items'][-1]['row'], 6)

    def test_export_vectors_alpha_dimensions_and_notices(self):
        from PIL import Image
        result = run({'action': 'export', 'icons': IDS, 'color': '#2563EB', 'size': 96})
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['data']['files']), len(IDS) * 2)
        for file in result['data']['files']:
            path = Path(file['path'])
            self.assertTrue(path.is_absolute())
            self.assertEqual(path.stat().st_size, file['size_bytes'])
            if file['format'] == 'png':
                with Image.open(path) as image:
                    self.assertEqual(image.size, (96, 96))
                    self.assertEqual(image.mode, 'RGBA')
                    self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
                    self.assertIsNotNone(image.getbbox())
            else:
                self.assertIn(b'#2563EB', path.read_bytes())
                self.assertNotIn(b'currentColor', path.read_bytes())
        for notice in result['data']['license_files']:
            path = Path(notice['path'])
            self.assertEqual(path.read_bytes(), (self.catalog.assets / 'licenses' / path.name).read_bytes())

    def test_coloring_preserves_none_fixed_colors_and_duotone_opacity(self):
        raw = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><path fill="none" stroke="currentColor"/><path fill="#ABCDEF" opacity="0.2"/></svg>'
        svg = styled_svg(raw, '#112233')
        root = ET.fromstring(svg)
        self.assertEqual(root[0].attrib, {'fill': 'none', 'stroke': '#112233'})
        self.assertEqual(root[1].attrib, {'fill': '#ABCDEF', 'opacity': '0.2'})
        record = self.catalog.select(['phosphor:duotone/gear-duotone'])[0]
        self.assertIn(b'opacity="0.2"', styled_svg(self.catalog.svg(record), '#112233'))

    def test_wide_svg_keeps_aspect_ratio_and_transparent_padding(self):
        raw = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20" fill="red"/></svg>'
        image = rasterize(raw, 100)
        self.assertEqual(image.size, (100, 100))
        self.assertEqual(image.getbbox(), (0, 25, 100, 75))

    def test_all_styles_rasterize(self):
        seen = set()
        for record in self.catalog.records:
            key = record['library'], record['style']
            if key in seen:
                continue
            seen.add(key)
            with self.subTest(style=key):
                image = rasterize(styled_svg(self.catalog.svg(record), None), 64)
                self.assertIsNotNone(image.getbbox())
        self.assertEqual(len(seen), sum(len(lib['styles']) for lib in self.catalog.libraries.values()))

    def test_partial_render_failure_reports_successful_svg_and_error(self):
        with patch('main.rasterize', side_effect=RuntimeError('simulated renderer error')):
            result = run({'action': 'export', 'icons': IDS[:1]})
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['data']['files']), 1)
        self.assertEqual(result['data']['files'][0]['format'], 'svg')
        self.assertEqual(result['data']['failures'][0]['format'], 'png')
        self.assertTrue(Path(result['data']['manifest']['path']).is_file())

    def test_failed_preview_does_not_claim_complete_or_write_output(self):
        with patch('rendering.rasterize', side_effect=RuntimeError('renderer error')):
            result = run({'action': 'preview', 'icons': IDS})
        self.assertFalse(result['ok'])
        self.assertFalse(list(self.folder.iterdir()))

    def test_concurrent_exports_do_not_overwrite(self):
        args = {'action': 'export', 'icons': IDS[:1], 'formats': ['svg']}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [args, args]))
        self.assertTrue(all(result['ok'] for result in results))
        paths = [r['data']['files'][0]['path'] for r in results]
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(Path(path).is_file() for path in paths))

    def test_no_workspace_requires_explicit_absolute_destination(self):
        with patch.dict(os.environ, {'TIANCE_WORKSPACE_ROOT': ''}):
            self.assertFalse(run({'action': 'export', 'icons': IDS[:1], 'formats': ['svg']})['ok'])
            self.assertFalse(run({'action': 'export', 'icons': IDS[:1], 'formats': ['svg'], 'output_dir': 'relative'})['ok'])
            self.assertTrue(run({'action': 'export', 'icons': IDS[:1], 'formats': ['svg'], 'output_dir': str(self.folder / 'explicit')})['ok'])

    def test_standalone_entry_requires_no_tiance_sdk(self):
        result = subprocess.run([sys.executable, str(ROOT / 'program/main.py')],
                                input=json.dumps({'action': 'search', 'queries': ['gear'], 'limit': 1}),
                                text=True, encoding='utf-8', capture_output=True, cwd=self.folder, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
