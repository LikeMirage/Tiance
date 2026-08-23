from __future__ import annotations

import os
import sys


DEFAULT_WINDOWS_APP_USER_MODEL_ID = "LikeMirage.Tiance"
WINDOWS_APP_USER_MODEL_ID_ENV = "TIANCE_APP_USER_MODEL_ID"


def configure_windows_process_app_identity() -> bool:
    if sys.platform != "win32":
        return False

    app_user_model_id = (
        os.getenv(WINDOWS_APP_USER_MODEL_ID_ENV, DEFAULT_WINDOWS_APP_USER_MODEL_ID).strip()
        or DEFAULT_WINDOWS_APP_USER_MODEL_ID
    )
    return _set_current_process_app_user_model_id(app_user_model_id)


def _set_current_process_app_user_model_id(app_user_model_id: str) -> bool:
    import ctypes

    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [ctypes.c_wchar_p]
    set_app_id.restype = ctypes.c_long
    return int(set_app_id(app_user_model_id)) >= 0
