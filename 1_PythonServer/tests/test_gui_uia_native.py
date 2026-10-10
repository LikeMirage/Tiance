"""Opt-in native regression: creates only its own temporary windows, never uses SendInput."""
import importlib.util
import json
import os
import subprocess
import sys
import ctypes
from ctypes import wintypes
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_gui_tool_suite import no_native_input


@pytest.mark.skipif(os.name != "nt" or os.environ.get("TIANCE_TEST_GUI_NATIVE") != "1",
                    reason="Set TIANCE_TEST_GUI_NATIVE=1 to show isolated native test windows")
def test_native_uia_controls_and_layered_popup_capture(tmp_path):
    base = tmp_path
    program = Path(__file__).resolve().parents[2] / 'Data/tools/c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21/program'
    def load(name):
        spec=importlib.util.spec_from_file_location(name, program/(name+'.py'))
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module
    helper=load('overlay_helper'); uia=load('uia_adapter')
    state_path=base/'uia-native-state.json'
    if state_path.exists(): state_path.unlink()
    proc=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass',
                          '-File',str(Path(__file__).with_name('fixtures')/'gui_uia_native.ps1'),'-StatePath',str(state_path)],
                         creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    adapter=uia.UiaAdapter(SimpleNamespace(cancel_event=threading.Event()),helper.GuiError,helper.window_info,
                           helper.foreground_window,helper.read_json,helper.atomic_json)
    state=None; report={}
    try:
        deadline=time.monotonic()+15
        while not state_path.exists() and proc.poll() is None and time.monotonic()<deadline: time.sleep(.1)
        if not state_path.exists():
            raise AssertionError('Fixture failed: '+(proc.stderr.read().decode(errors='replace') if proc.poll() is not None else 'startup timeout'))
        state=json.loads(state_path.read_text(encoding='utf-8-sig')); hwnd=state['hwnd']; pid=state['process_id']
        assert helper.activate_window(hwnd,timeout_ms=2000)
        result=adapter._query({'operation':'inspect','hwnd':hwnd,'process_id':pid},10)
        records=result['elements']
        assert isinstance(records,list) and all(isinstance(r,dict) for r in records), records
        report['controls']=[{'name':r['name'],'id':r['automation_id'],'patterns':r['patterns']} for r in records]
        worker_pid=adapter.process.pid
        def record(name):
            matches=[r for r in records if r['name']==name or r['automation_id']==name]
            assert matches, (name,records)
            return matches[0]
        def call(operation, item, **kw):
            if operation in uia.MUTATIONS:
                assert helper.activate_window(hwnd, timeout_ms=2000)
            expected={k:item[k] for k in ('runtime_id','process_id','name','automation_id','control_type','class_name')}
            return adapter._query({'operation':operation,'hwnd':hwnd,'process_id':pid,'expected':expected,**kw},10)
        edit=record('Test input'); check=record('Toggle test'); button=record('Invoke test')
        call('set_value',edit,value='中文 UIA test')
        assert call('read',edit)['element']['value']=='中文 UIA test'
        call('focus',edit); assert call('read',edit)['element']['focused']
        call('toggle',check); assert call('read',check)['element']['toggle_state']=='On'
        call('select',record('Second item')); assert call('read',record('Second item'))['element']['selected']
        parent=record('Parent node')
        call('expand',parent); assert call('read',parent)['element']['expand_state']=='Expanded'
        call('collapse',parent); assert call('read',parent)['element']['expand_state']=='Collapsed'
        call('invoke',button); time.sleep(.2); assert call('read',edit)['element']['value']=='invoked'
        assert adapter.process.pid==worker_pid
        report['native_actions']='set_value, read, focus, toggle, select, expand, collapse, invoke passed; one worker reused'
        try: call('toggle',edit)
        except helper.GuiError as error:
            assert error.code=='UIA_ACTION_UNSUPPORTED' and error.details['execution_status']=='not_started'
        else: raise AssertionError('Unsupported action unexpectedly accepted')
        assert adapter.process.pid==worker_pid
        bad={**edit,'runtime_id':'missing'}
        try: call('read',bad)
        except helper.GuiError as error: assert error.code=='UIA_ELEMENT_STALE'
        else: raise AssertionError('Missing reference unexpectedly accepted')
        windows=helper.visible_windows()
        assert any(w['hwnd']==state['popup'] and w['title']=='' for w in windows)
        assert helper.resolve_window(state['popup'],None)['owner_hwnd']==hwnd
        assert state['excluded']
        service=helper.GuiService.__new__(helper.GuiService)
        service._detect_capture_mode=lambda:'exclude_from_capture'
        assert helper.activate_window(hwnd, timeout_ms=2000)
        time.sleep(.2)
        rect=helper.window_rect(hwnd); shot=service._capture_bbox(rect)
        blue=shot.getpixel((550-rect['left'],500-rect['top']))
        excluded=shot.getpixel((720-rect['left'],500-rect['top']))
        assert blue[2]>180 and blue[2]>blue[0]+100, blue
        assert min(excluded)>220, excluded
        report['capture']={'layered_popup_rgb':blue,'excluded_overlay_rgb':excluded,'untitled_popup_listed':True}
        report['passed']=True
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        adapter.close()
        if state is not None and proc.poll() is None:
            helper.user32.PostMessageW(state['hwnd'],0x10,0,0)
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)
        proc.stdout.close(); proc.stderr.close()


@pytest.mark.skipif(os.name != "nt" or os.environ.get("TIANCE_TEST_GUI_NATIVE") != "1",
                    reason="Native worker ownership test")
def test_worker_exits_when_owning_runtime_is_killed():
    path = Path(__file__).resolve().parents[2] / 'Data/tools/c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21/program/uia_adapter.py'
    script = '''
import importlib.util, sys
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('adapter',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
adapter=module.UiaAdapter(SimpleNamespace(),RuntimeError,None,None,None,None)
adapter._start()
print(adapter.process.pid,flush=True)
sys.stdin.read()
'''
    owner = subprocess.Popen([sys.executable, '-c', script, str(path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    child = None
    try:
        child_id = int(owner.stdout.readline())
        child = api.OpenProcess(0x00100001, False, child_id)  # SYNCHRONIZE | TERMINATE
        assert child
        owner.kill(); owner.wait(timeout=3)
        assert api.WaitForSingleObject(child, 3000) == 0
    finally:
        if owner.poll() is None:
            owner.kill(); owner.wait(timeout=3)
        if child:
            if api.WaitForSingleObject(child, 0) != 0: api.TerminateProcess(child, 1)
            api.CloseHandle(child)
        for pipe in (owner.stdin, owner.stdout, owner.stderr): pipe.close()
