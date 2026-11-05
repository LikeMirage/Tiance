from __future__ import annotations

import ctypes
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_transcribe import ROOT
from jianying_asr.common import ASRError, Budget, atomic_replace, write_json


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'job.json'
        write_json(self.path, {'status':'before'})

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_actual_windows_reader_releases_then_checkpoint_succeeds(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,
                                      ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(self.path),0x80000000,3,None,3,128,None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        released = threading.Event()
        def release():
            kernel.CloseHandle(handle)
            released.set()
        timer = threading.Timer(0.12, release)
        timer.start()
        try:
            write_json(self.path, {'status':'after'}, budget=Budget(10))
            self.assertTrue(released.is_set())
            self.assertEqual(json.loads(self.path.read_text())['status'],'after')
        finally:
            timer.join()
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_persistent_denial_preserves_old_checkpoint_and_raises(self):
        error = PermissionError('persistent denial')
        error.winerror = 5
        with patch('jianying_asr.common.os.replace',side_effect=error) as replaced, \
                patch('jianying_asr.common.time.sleep'):
            with self.assertRaises(PermissionError): write_json(self.path, {'status':'after'})
        self.assertEqual(replaced.call_count,6)
        self.assertEqual(json.loads(self.path.read_text())['status'],'before')
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_other_error_not_retried_and_budget_not_extended(self):
        with patch('jianying_asr.common.os.replace',side_effect=OSError('disk failure')) as replaced:
            with self.assertRaises(OSError): write_json(self.path, {'x':1})
        self.assertEqual(replaced.call_count,1)
        error = PermissionError('sharing')
        error.winerror = 32
        budget = Budget(10)
        budget.deadline = time.monotonic()+0.01
        with patch('jianying_asr.common.os.replace',side_effect=error):
            with self.assertRaises(ASRError): write_json(self.path, {'x':2},budget=budget)
        self.assertEqual(json.loads(self.path.read_text())['status'],'before')


if __name__ == '__main__': unittest.main()
