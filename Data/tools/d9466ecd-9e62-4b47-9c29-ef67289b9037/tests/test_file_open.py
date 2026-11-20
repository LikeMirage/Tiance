import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
sys.path[:0] = [str(ROOT / 'program'), str(REPO / '1_PythonServer')]
import main
import windows_shell
from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_permissions import evaluate_tool_permissions
from app.services.tools.tool_metadata import load_tool, standard_tool_description, example_detail
from app.infra.tools.tool_project_config_storage import ToolProjectConfigStorage


class FileOpenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tiance-file-open-')
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.file = self.workspace / "中文 空格 & $测试.json"
        self.file.write_text('{"测试":true}', encoding='utf-8')
        self.env = patch.dict(os.environ, {'TIANCE_WORKSPACE_ROOT': str(self.workspace)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.shell = MagicMock()
        self.shell.__enter__.return_value = self.shell
        self.shell.default_app.return_value = {'registered': True, 'app_name': 'Test Editor'}
        self.shell.list_apps.return_value = ({'applications': [], 'default_app': {}, 'enumeration_complete': True}, [])
        self.shell.open_with_handler.return_value = {'name': 'Test Editor'}
        self.mock = patch.object(main, 'WindowsShell', return_value=self.shell)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def call(self, action, **kwargs):
        return main.run(dict(action=action, path=self.file.name, **kwargs))

    def test_queries_have_no_open_side_effects(self):
        for action in ('get_default_app', 'list_apps'):
            with self.subTest(action=action):
                result = self.call(action)
                self.assertTrue(result['ok'])
                self.assertEqual(result['data']['status'], 'queried')
                self.assertEqual(result['data']['path'], str(self.file))
        for method in ('open_default', 'open_with_handler', 'open_with_executable', 'reveal'):
            getattr(self.shell, method).assert_not_called()

    def test_reveal_file_and_directory(self):
        self.assertTrue(self.call('reveal')['ok'])
        self.shell.reveal.assert_called_with(self.file)
        result = main.run({'action': 'reveal', 'path': '.'})
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['selection_requested'])
        self.shell.reveal.assert_called_with(self.workspace)

    def test_default_open_is_not_overridden_by_an_office_app(self):
        result = self.call('open_default')
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['status'], 'submitted')
        self.shell.open_default.assert_called_once_with(self.file)
        self.shell.default_app.assert_not_called()
        self.shell.open_with_executable.assert_not_called()

    def test_specified_handler_is_forwarded_verbatim(self):
        identifier = 'windows:' + 'a' * 64
        self.assertTrue(self.call('open_with', application_id=identifier)['ok'])
        self.shell.open_with_handler.assert_called_once_with(self.file, identifier)

    def test_stale_handler_does_not_fall_back_to_default(self):
        self.shell.open_with_handler.side_effect = windows_shell.ShellError('APPLICATION_NOT_AVAILABLE', '刷新列表')
        result = self.call('open_with', application_id='windows:' + 'b' * 64)
        self.assertEqual(result['error_info']['code'], 'APPLICATION_NOT_AVAILABLE')
        self.shell.open_default.assert_not_called()

    def test_no_association_is_a_structured_error(self):
        error = OSError('No association')
        error.winerror = 1155
        self.shell.open_default.side_effect = error
        self.assertEqual(self.call('open_default')['error_info']['code'], 'NO_ASSOCIATION')

    def test_directory_rejected_except_reveal(self):
        for action in main.ACTIONS - {'reveal'}:
            payload = {'action': action, 'path': '.'}
            if action == 'open_with':
                payload['application_id'] = 'windows:' + 'a' * 64
            self.assertEqual(main.run(payload)['error_info']['code'], 'IS_DIRECTORY')

    def test_unknown_extra_and_conflicting_parameters_fail_before_activation(self):
        invalid = [
            {}, {'action': 'bad', 'path': self.file.name},
            {'action': 'open_default', 'path': self.file.name, 'extra': True},
            {'action': 'open_with', 'path': self.file.name},
            {'action': 'open_with', 'path': self.file.name, 'application_id': 'VS Code'},
            {'action': 'open_with', 'path': self.file.name, 'application_id': 'windows:'+'a'*64, 'application_path': 'C:/test.exe'},
            {'action': 'list_apps', 'path': self.file.name, 'application_path': 'C:/test.exe'},
            {'action': 'reveal', 'path': 123}, {'action': 'reveal', 'path': 'a\0b'},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(main.run(payload)['error_info']['code'], 'INVALID_ARGUMENT')
        self.shell.__enter__.assert_not_called()

    def test_missing_file_and_ambiguous_paths(self):
        for path, code in [('missing.json', 'PATH_NOT_FOUND'), ('C:relative.json', 'INVALID_PATH'),
                           ('\\rooted.json', 'INVALID_PATH'), ('https://example.org/a.json', 'INVALID_PATH'),
                           ('shell:AppsFolder', 'INVALID_PATH'), (str(self.file)+':stream', 'INVALID_PATH')]:
            with self.subTest(path=path):
                self.assertEqual(main.run({'action': 'reveal', 'path': path})['error_info']['code'], code)

    def test_no_workspace_does_not_fall_back_to_cwd(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.call('reveal')['error_info']['code'], 'WORKSPACE_REQUIRED')
            self.assertTrue(main.run({'action': 'reveal', 'path': str(self.file)})['ok'])

    def test_application_path_requires_a_real_absolute_executable(self):
        for path in ['notepad.exe', str(self.file), str(self.workspace), 'C:/missing-open-file.exe']:
            with self.subTest(path=path):
                self.assertFalse(self.call('open_with', application_path=path)['ok'])
        executable = self.workspace / '测试 editor.exe'
        executable.write_bytes(b'fixture; launch mocked')
        self.shell.open_with_executable.return_value = {'name': '测试'}
        self.assertTrue(self.call('open_with', application_path=str(executable))['ok'])
        self.shell.open_with_executable.assert_called_once_with(self.file, executable)

    def test_external_absolute_and_symlink_paths_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'outside.json'
            target.write_text('{}')
            self.assertTrue(main.run({'action': 'get_default_app', 'path': str(target)})['ok'])
            link = self.workspace / 'linked.json'
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest('Windows symbolic link permission unavailable')
            self.assertEqual(main.resolve_path('linked.json'), target)
            evaluation = self.permissions({'action': 'get_default_app', 'path': 'linked.json'})
            self.assertTrue(any(f.scope == 'workspace_outside' for f in evaluation.facts))

    def permissions(self, arguments, root=ROOT):
        schema = json.loads((root/'.tool/input.schema.json').read_text(encoding='utf-8'))
        return evaluate_tool_permissions(tool_name='open_system_file', arguments=arguments, input_schema=schema,
                                         tool_root=str(root), workspace_root=str(self.workspace), project_id='test')

    def test_execution_and_external_read_permissions_are_visible_and_deny_wins(self):
        result = self.permissions({'action': 'open_default', 'path': str(REPO/'README.md')})
        self.assertTrue(any(f.permission_type == 'program_execute' and f.scope == 'system_program' for f in result.facts))
        self.assertTrue(any(f.permission_type == 'filesystem_read' and f.scope == 'workspace_outside' for f in result.facts))
        tool = self.workspace/'tool'
        (tool/'.tool').mkdir(parents=True)
        for name in ('input.schema.json', 'permissions.json'):
            (tool/'.tool'/name).write_bytes((ROOT/'.tool'/name).read_bytes())
        policy = json.loads((tool/'.tool/permissions.json').read_text(encoding='utf-8'))
        policy['policies']['program_execute']['system_program'] = 'deny'
        (tool/'.tool/permissions.json').write_text(json.dumps(policy))
        self.assertEqual(self.permissions({'action': 'open_default', 'path': self.file.name}, tool).decision, 'deny')


class NativeContractTests(unittest.TestCase):
    def test_application_identifier_is_stable_but_bound_to_extension(self):
        identify = windows_shell.application_id
        self.assertEqual(identify('.JSON', 'Test.EXE', None), identify('.json', 'test.exe', None))
        self.assertNotEqual(identify('.txt', 'test.exe', None), identify('.json', 'test.exe', None))

    def test_default_identity_supports_packaged_apps_and_unknown_identity(self):
        default = {'registered': True, 'progid': 'AppX123', 'executable_path': None, 'app_user_model_id': 'Package!App'}
        app = {'progid': 'AppX123', 'executable_path': None, 'handler_name': 'Package!App'}
        self.assertTrue(windows_shell.default_match(app, default))
        app.update(progid=None, handler_name='unknown')
        self.assertIsNone(windows_shell.default_match(app, default))

    def test_application_launch_uses_argument_array_and_does_not_leak_host_environment(self):
        target = Path('C:/中文 & $路径/文件.json')
        executable = Path('C:/Program Files/Test/editor.exe')
        with patch.dict(os.environ, {'TIANCE_HOST_CAPABILITY_TOKEN': 'secret-test', 'PYTHONPATH': 'host-test', 'NORMAL_TEST': 'kept'}):
            with patch.object(windows_shell.subprocess, 'Popen') as launch:
                launch.return_value.pid = 123
                Windows = windows_shell.WindowsShell()
                self.assertEqual(Windows.open_with_executable(target, executable)['process_id'], 123)
                args, kwargs = launch.call_args
                self.assertEqual(args[0], [str(executable), str(target)])
                self.assertNotIn('TIANCE_HOST_CAPABILITY_TOKEN', kwargs['env'])
                self.assertNotIn('PYTHONPATH', kwargs['env'])
                self.assertEqual(kwargs['env']['NORMAL_TEST'], 'kept')
                self.assertNotIn('shell', kwargs)
            with self.assertRaises(RuntimeError):
                with windows_shell.application_environment():
                    self.assertNotIn('TIANCE_HOST_CAPABILITY_TOKEN', os.environ)
                    raise RuntimeError('test')
            self.assertEqual(os.environ['TIANCE_HOST_CAPABILITY_TOKEN'], 'secret-test')

    def test_standard_files_examples_and_actual_platform_validator(self):
        storage = ToolProjectConfigStorage()
        for name in ('tool.json', 'input.schema.json', 'output.schema.json', 'examples.json', 'permissions.json'):
            storage.normalize_standard_file_content('.tool/'+name, (ROOT/'.tool'/name).read_text(encoding='utf-8'))
        tool = load_tool(str(ROOT))
        self.assertEqual(tool.name, 'open_system_file')
        for _, example in tool.examples:
            content = example['content']
            if content.startswith('{'):
                self.assertEqual(validate_tool_arguments(json.loads(content), tool.input_schema), [])
        invalid = [{'action': 'open_with', 'path': 'a.json'},
                   {'action': 'open_default', 'path': 'a.json', 'application_path': 'C:/test.exe'},
                   {'action': 'open_with', 'path': 'a.json', 'application_path': 'C:/test.exe', 'application_id': 'windows:'+'a'*64},
                   {'action': 'reveal', 'path': 'a.json', 'unexpected': 1}]
        for payload in invalid:
            self.assertTrue(validate_tool_arguments(payload, tool.input_schema), payload)
        valid = {'action': 'open_with', 'path': 'a.json', 'application_id': 'windows:'+'a'*64}
        self.assertEqual(validate_tool_arguments(valid, tool.input_schema), [])
        description = standard_tool_description(tool.manifest['description'], tuple(example_detail(i,e) for i,e in tool.examples))
        self.assertIn('submitted', description)
        self.assertIn('手机', description)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native API')
    def test_actual_windows_read_only_queries_and_stale_id(self):
        with windows_shell.WindowsShell() as shell:
            default = shell.default_app('.txt')
            self.assertIsInstance(default['registered'], bool)
            result, warnings = shell.list_apps('.json')
            self.assertIsInstance(result['applications'], list)
            self.assertEqual(len({a['application_id'] for a in result['applications']}), len(result['applications']))
            result, warnings = shell.list_apps('')
            self.assertEqual(result['applications'], [])
            self.assertTrue(warnings)
            with self.assertRaises(windows_shell.ShellError) as exc:
                shell.open_with_handler(REPO/'README.md', 'windows:'+'0'*64)
            self.assertEqual(exc.exception.code, 'APPLICATION_NOT_AVAILABLE')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native API')
    def test_real_subprocess_protocol_queries_and_rejects_invalid_input(self):
        env = dict(os.environ, PYTHONPATH=str(REPO/'1_PythonServer'), PYTHONIOENCODING='utf-8')
        for payload, ok in [({'action':'get_default_app','path':str(ROOT/'README.md')}, True),
                            ({'action':'open_with','path':str(ROOT/'README.md')}, False)]:
            result = subprocess.run([sys.executable, str(ROOT/'program/main.py')],
                                    input=json.dumps(payload, ensure_ascii=False), encoding='utf-8',
                                    capture_output=True, env=env, timeout=30)
            output = json.loads(result.stdout)
            self.assertEqual(output['ok'], ok)
            self.assertEqual(result.returncode == 0, ok)
            schema = json.loads((ROOT/'.tool/output.schema.json').read_text(encoding='utf-8'))
            self.assertEqual(validate_tool_arguments(output, schema), [])


if __name__ == '__main__':
    unittest.main()
