from __future__ import annotations

from app import windows_app_identity


def test_non_windows_process_does_not_configure_application_identity(monkeypatch) -> None:
    monkeypatch.setattr(windows_app_identity.sys, "platform", "linux")

    assert windows_app_identity.configure_windows_process_app_identity() is False


def test_windows_process_uses_identity_supplied_by_launcher(monkeypatch) -> None:
    configured_identities: list[str] = []
    monkeypatch.setattr(windows_app_identity.sys, "platform", "win32")
    monkeypatch.setenv(windows_app_identity.WINDOWS_APP_USER_MODEL_ID_ENV, "Example.CustomIdentity")
    monkeypatch.setattr(
        windows_app_identity,
        "_set_current_process_app_user_model_id",
        lambda value: configured_identities.append(value) or True,
    )

    assert windows_app_identity.configure_windows_process_app_identity() is True
    assert configured_identities == ["Example.CustomIdentity"]


def test_windows_process_uses_tiance_identity_when_environment_value_is_blank(monkeypatch) -> None:
    configured_identities: list[str] = []
    monkeypatch.setattr(windows_app_identity.sys, "platform", "win32")
    monkeypatch.setenv(windows_app_identity.WINDOWS_APP_USER_MODEL_ID_ENV, "   ")
    monkeypatch.setattr(
        windows_app_identity,
        "_set_current_process_app_user_model_id",
        lambda value: configured_identities.append(value) or True,
    )

    assert windows_app_identity.configure_windows_process_app_identity() is True
    assert configured_identities == [windows_app_identity.DEFAULT_WINDOWS_APP_USER_MODEL_ID]
