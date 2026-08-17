from __future__ import annotations

import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4

from tiance_runtime import run_tool

from app.core.config import get_settings
from app.repositories.themes import get_theme_settings_repository
from app.schemas.themes import ThemeDefinition
from app.services.themes import get_active_theme_id, get_theme, set_active_theme

from palette import PaletteError, derive_theme_palette


THEME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FIELD_PART_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
RESTORABLE_THEME_IDS = ("dark-gold", "light")
THEME_SETTINGS_FILE = "theme-settings.json"
THEME_MANIFEST_FILE = "theme.json"
BACKGROUND_IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
THEME_PARAMETER_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("surface_base", "tokens.color.surface.base", "应用主背景色。"),
    ("surface_panel", "tokens.color.surface.panel", "普通面板、项目卡片、设置面板主体背景。"),
    ("surface_panel_alt", "tokens.color.surface.panelAlt", "次级面板、卡片内部内容区背景。"),
    ("surface_toolbar", "tokens.color.surface.toolbar", "工具栏、标签栏等横向操作区背景。"),
    ("surface_titlebar", "tokens.color.surface.titlebar", "窗口顶边栏背景。"),
    ("surface_statusbar", "tokens.color.surface.statusbar", "底部状态栏背景。"),
    ("surface_sidebar", "tokens.color.surface.sidebar", "左侧侧边栏、列表栏背景。"),
    ("surface_canvas", "tokens.color.surface.canvas", "主工作区画布背景。"),
    ("surface_elevated", "tokens.color.surface.elevated", "浮层、弹出面板、悬浮卡片背景。"),
    ("surface_muted", "tokens.color.surface.muted", "弱化区块、非重点区域背景。"),
    ("surface_overlay", "tokens.color.surface.overlay", "覆盖层、轻遮罩背景。"),
    ("surface_menu", "tokens.color.surface.menu", "右键菜单、下拉菜单背景。"),
    ("surface_input", "tokens.color.surface.input", "输入框、搜索框默认背景。"),
    ("surface_input_hover", "tokens.color.surface.inputHover", "输入框悬浮或聚焦前的背景。"),
    ("surface_item_hover", "tokens.color.surface.itemHover", "列表项、菜单项普通悬浮背景。"),
    ("surface_item_hover_strong", "tokens.color.surface.itemHoverStrong", "列表项、菜单项强悬浮或激活背景。"),
    ("text_primary", "tokens.color.text.primary", "主文字颜色。"),
    ("text_secondary", "tokens.color.text.secondary", "次级文字颜色。"),
    ("text_muted", "tokens.color.text.muted", "弱化说明、时间、次要计数文字颜色。"),
    ("text_heading", "tokens.color.text.heading", "标题文字颜色。"),
    ("text_heading_accent", "tokens.color.text.headingAccent", "带主题强调的标题文字颜色。"),
    ("text_inverse", "tokens.color.text.inverse", "反色文字颜色，用于深浅反差按钮或选中块。"),
    ("text_selection_text", "tokens.color.text.selectionText", "文字被系统选中后的前景色。"),
    ("border_soft", "tokens.color.border.soft", "普通卡片、输入框、面板的柔和边框。"),
    ("border_subtle", "tokens.color.border.subtle", "更弱的分割边框。"),
    ("border_strong", "tokens.color.border.strong", "强调边框、重要区域边框。"),
    ("border_focus", "tokens.color.border.focus", "输入框、按钮、控件聚焦边框。"),
    ("border_separator", "tokens.color.border.separator", "组件内部的普通分割线。"),
    ("accent_base", "tokens.color.accent.base", "主题主强调色，按钮、图标、重点文字常用。"),
    ("accent_rgb", "tokens.color.accent.rgb", "主题主强调色 RGB 三段数字，例如 222, 160, 89。"),
    ("accent_hover", "tokens.color.accent.hover", "强调元素悬浮颜色。"),
    ("accent_text", "tokens.color.accent.text", "普通强调文字颜色。"),
    ("accent_soft_text", "tokens.color.accent.softText", "弱化强调文字颜色。"),
    ("accent_selection_text", "tokens.color.accent.selectionText", "主题选中态文字颜色。"),
    ("accent_selection_bg_subtle", "tokens.color.accent.selectionBgSubtle", "轻选中背景。"),
    ("accent_selection_bg", "tokens.color.accent.selectionBg", "标准选中背景。"),
    ("accent_selection_bg_hover", "tokens.color.accent.selectionBgHover", "选中项悬浮背景。"),
    ("accent_selection_border", "tokens.color.accent.selectionBorder", "选中卡片、选中会话、重点项边框。"),
    ("accent_text_selection_bg", "tokens.color.accent.textSelectionBg", "系统文字选区背景。"),
    ("state_danger", "tokens.color.state.danger", "危险状态主色。"),
    ("state_danger_text", "tokens.color.state.dangerText", "危险操作文字颜色。"),
    ("state_danger_soft_text", "tokens.color.state.dangerSoftText", "弱化危险提示文字颜色。"),
    ("state_danger_bg", "tokens.color.state.dangerBg", "危险提示背景。"),
    ("state_danger_border", "tokens.color.state.dangerBorder", "危险提示边框。"),
    ("state_warning", "tokens.color.state.warning", "警告状态主色。"),
    ("state_warning_text", "tokens.color.state.warningText", "警告文字颜色。"),
    ("state_success", "tokens.color.state.success", "成功状态主色。"),
    ("state_success_text", "tokens.color.state.successText", "成功文字颜色。"),
    ("collapse_fade_start", "tokens.color.collapse.fadeStart", "折叠渐隐起始颜色。"),
    ("collapse_fade_mid", "tokens.color.collapse.fadeMid", "折叠渐隐中段颜色。"),
    ("collapse_fade_end", "tokens.color.collapse.fadeEnd", "折叠渐隐结束颜色。"),
    ("collapse_caret", "tokens.color.collapse.caret", "折叠展开箭头颜色。"),
    ("scrollbar_track", "tokens.color.scrollbar.track", "滚动条轨道颜色。"),
    ("scrollbar_thumb", "tokens.color.scrollbar.thumb", "滚动条滑块颜色。"),
    ("scrollbar_thumb_hover", "tokens.color.scrollbar.thumbHover", "滚动条滑块悬浮颜色。"),
    ("structure_color", "tokens.structure.color", "界面主要结构线的默认颜色。"),
    ("structure_hover_color", "tokens.structure.hoverColor", "可拖拽结构线悬浮时的颜色。"),
    ("structure_active_color", "tokens.structure.activeColor", "可拖拽结构线按下时的颜色。"),
    ("shadow_floating", "tokens.shadow.floating", "浮层阴影。"),
    ("shadow_panel", "tokens.shadow.panel", "面板阴影。"),
    ("editor_background", "tokens.editor.background", "代码编辑器背景。"),
    ("editor_foreground", "tokens.editor.foreground", "代码编辑器正文颜色。"),
    ("editor_gutter_background", "tokens.editor.gutterBackground", "代码编辑器行号栏背景。"),
    ("editor_gutter_foreground", "tokens.editor.gutterForeground", "代码编辑器行号文字颜色。"),
    ("editor_active_line", "tokens.editor.activeLine", "代码编辑器当前行背景。"),
    ("editor_selection_match", "tokens.editor.selectionMatch", "代码编辑器搜索匹配或选区匹配背景。"),
    ("editor_tooltip_background", "tokens.editor.tooltipBackground", "代码编辑器提示浮层背景。"),
    ("integration_code_mirror", "integrations.codeMirror", "CodeMirror 主题模式。"),
    ("integration_shiki", "integrations.shiki", "Shiki 代码高亮主题名。"),
    ("integration_mermaid", "integrations.mermaid", "Mermaid 图表主题名。"),
    ("integration_milkdown", "integrations.milkdown", "Milkdown Markdown 编辑器主题名。"),
)
THEME_BOOLEAN_PARAMETER_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("structure_enabled", "tokens.structure.enabled", "是否显示该主题的全部结构线。"),
    ("structure_titlebar_bottom", "tokens.structure.lines.titlebarBottom", "是否显示顶边栏底部结构线。"),
    ("structure_statusbar_top", "tokens.structure.lines.statusbarTop", "是否显示底边栏顶部结构线。"),
    ("structure_navigation_right", "tokens.structure.lines.navigationRight", "是否显示左侧导航右侧结构线。"),
    ("structure_side_panel_right", "tokens.structure.lines.sidePanelRight", "是否显示左侧面板右侧结构线。"),
    ("structure_assistant_panel_left", "tokens.structure.lines.assistantPanelLeft", "是否显示右侧对话面板左侧结构线。"),
    ("structure_content_split", "tokens.structure.lines.contentSplit", "是否显示编辑预览、工具区等内容分栏结构线。"),
)
THEME_INTEGER_PARAMETER_FIELDS: tuple[tuple[str, str, str, int, int], ...] = (
    ("structure_width", "tokens.structure.width", "结构线宽度，单位为像素。", 1, 2),
)


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def success(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        action = read_action(payload.get("action"))
        if action == "list":
            result = list_themes_action()
        elif action == "get_current":
            result = get_current_theme_action()
        elif action == "create":
            result = create_theme(payload)
        elif action == "clone":
            result = clone_theme(payload)
        elif action == "derive_palette":
            result = derive_palette_action(payload)
        elif action == "edit":
            result = edit_theme(payload)
        elif action == "switch":
            result = switch_theme(payload)
        elif action == "restore":
            result = restore_themes(payload)
        elif action == "delete":
            result = delete_theme(payload)
        else:
            raise ToolError("INVALID_ARGUMENT", "action 参数无效。")
        if action in {"create", "clone", "derive_palette", "edit", "switch", "restore", "delete"}:
            result["resource_invalidations"] = [
                {"resource": "themes", "scope": "global"}
            ]
        return result
    except ToolError as exc:
        return failure(exc.code, exc.message, exc.details)
    except Exception as exc:
        return failure("UNEXPECTED_ERROR", "主题工具执行失败。", {"error": str(exc)})


def list_themes_action() -> dict[str, Any]:
    theme_dir = get_settings().themes_data_path
    if not theme_dir.is_dir():
        raise ToolError("THEME_DIR_NOT_FOUND", "主题目录不存在。", {"theme_dir": str(theme_dir)})

    active_theme_id = get_theme_settings_repository().get_active_theme_id()
    themes: list[dict[str, Any]] = []
    skipped_packages: list[dict[str, str]] = []

    for package_dir in sorted(theme_dir.iterdir(), key=lambda item: item.name.lower()):
        if not package_dir.is_dir():
            continue
        theme_id = package_dir.name
        if not THEME_ID_PATTERN.fullmatch(theme_id):
            skipped_packages.append(
                {
                    "package_name": package_dir.name,
                    "theme_package_path": str(package_dir),
                    "reason": "目录名不是合法主题 ID。",
                }
            )
            continue

        path = theme_file_path(theme_id)
        try:
            theme_payload = read_theme_payload(path, expected_id=theme_id)
        except ToolError as exc:
            skipped_packages.append(
                {
                    "package_name": package_dir.name,
                    "theme_package_path": str(package_dir),
                    "theme_file_path": str(path),
                    "reason": exc.message,
                    "code": exc.code,
                }
            )
            continue

        themes.append(
            {
                "theme_id": str(theme_payload["id"]),
                "theme_name": str(theme_payload["name"]),
                "mode": str(theme_payload["mode"]),
                "active": theme_payload["id"] == active_theme_id,
            }
        )

    warnings = []
    if skipped_packages:
        warnings.append(f"已跳过 {len(skipped_packages)} 个不可用主题包。")

    return success(
        f"找到 {len(themes)} 个可用主题。",
        {
            "action": "list",
            "active_theme_id": active_theme_id,
            "themes": themes,
            "skipped_packages": skipped_packages,
        },
        warnings,
    )


def get_current_theme_action() -> dict[str, Any]:
    active_theme_id = get_theme_settings_repository().get_active_theme_id()
    path = existing_theme_path(active_theme_id)
    theme_payload = read_theme_payload(path, expected_id=active_theme_id)
    color_tokens = theme_payload["tokens"]["color"]
    return success(
        f"当前主题是 {theme_payload['name']}（{active_theme_id}）。",
        {
            "action": "get_current",
            "theme_id": active_theme_id,
            "theme_name": str(theme_payload["name"]),
            "mode": str(theme_payload["mode"]),
            "accent_base": str(color_tokens["accent"]["base"]),
            "surface_base": str(color_tokens["surface"]["base"]),
            "text_primary": str(color_tokens["text"]["primary"]),
        },
    )


def create_theme(payload: dict[str, Any]) -> dict[str, Any]:
    theme_id = read_theme_id(payload.get("theme_id"), field_name="theme_id")
    theme_name = read_non_empty_string(payload.get("theme_name"), field_name="theme_name")
    target_path = theme_file_path(theme_id)
    if target_path.exists():
        raise ToolError("THEME_ID_EXISTS", "同 ID 的主题文件已存在。", {"theme_file_path": str(target_path)})
    package_path = theme_package_path(theme_id)
    if package_path.exists():
        raise ToolError("THEME_ID_EXISTS", "同 ID 的主题包目录已存在。", {"theme_package_path": str(package_path)})

    next_payload = build_theme_payload_from_parameters(theme_id, theme_name, payload)
    background_result = apply_background_updates(next_payload, payload, theme_id)
    validate_theme_payload(next_payload, expected_id=theme_id)
    write_theme_payload(target_path, next_payload)
    saved = read_theme_payload(target_path, expected_id=theme_id)
    return success(
        f"已创建主题 {theme_name}（{theme_id}）。",
        {
            "action": "create",
            "theme_id": theme_id,
            "theme_name": saved["name"],
            "theme_package_path": str(package_path),
            "theme_file_path": str(target_path),
            "background": background_result["background"],
            "activated": False,
        },
    )


def clone_theme(payload: dict[str, Any]) -> dict[str, Any]:
    source_theme_id = read_theme_id(payload.get("source_theme_id"), field_name="source_theme_id")
    theme_id = read_theme_id(payload.get("theme_id"), field_name="theme_id")
    theme_name = read_non_empty_string(payload.get("theme_name"), field_name="theme_name")
    source_path = existing_theme_path(source_theme_id)
    source_package_path = theme_package_path(source_theme_id)
    target_package_path = theme_package_path(theme_id)
    target_path = target_package_path / THEME_MANIFEST_FILE
    if target_package_path.exists():
        raise ToolError(
            "THEME_ID_EXISTS",
            "同 ID 的主题包目录已存在。",
            {"theme_package_path": str(target_package_path)},
        )

    source_payload = read_theme_payload(source_path, expected_id=source_theme_id)
    next_payload = deepcopy(source_payload)
    next_payload["id"] = theme_id
    next_payload["name"] = theme_name
    changed_fields = ["id", "name"]

    for field_path, value in read_theme_parameter_updates(payload).items():
        apply_field_update(next_payload, field_path, value)
        changed_fields.append(field_path)

    theme_root = get_settings().themes_data_path
    temporary_package_path = theme_root / f".{theme_id}.{uuid4().hex}.tmp"
    try:
        shutil.copytree(source_package_path, temporary_package_path)
        background_result = apply_background_updates(
            next_payload,
            payload,
            theme_id,
            package_path=temporary_package_path,
        )
        changed_fields.extend(background_result["changed_fields"])
        validate_theme_payload(next_payload, expected_id=theme_id)
        temporary_theme_path = temporary_package_path / THEME_MANIFEST_FILE
        write_theme_payload(temporary_theme_path, next_payload)
        read_theme_payload(temporary_theme_path, expected_id=theme_id)
        if target_package_path.exists():
            raise ToolError(
                "THEME_ID_EXISTS",
                "同 ID 的主题包目录已存在。",
                {"theme_package_path": str(target_package_path)},
            )
        os.replace(temporary_package_path, target_package_path)
    except ToolError:
        raise
    except OSError as exc:
        raise ToolError(
            "CLONE_THEME_FAILED",
            "无法复制主题包。",
            {
                "source_theme_id": source_theme_id,
                "theme_id": theme_id,
                "source_theme_package_path": str(source_package_path),
                "theme_package_path": str(target_package_path),
                "error": str(exc),
            },
        ) from exc
    finally:
        if temporary_package_path.exists():
            try:
                shutil.rmtree(temporary_package_path)
            except OSError:
                pass

    saved = read_theme_payload(target_path, expected_id=theme_id)
    copied_asset_count = count_theme_asset_files(target_package_path)
    return success(
        f"已克隆主题 {source_theme_id} 为 {theme_name}（{theme_id}）。",
        {
            "action": "clone",
            "source_theme_id": source_theme_id,
            "theme_id": theme_id,
            "theme_name": saved["name"],
            "theme_package_path": str(target_package_path),
            "theme_file_path": str(target_path),
            "copied_asset_count": copied_asset_count,
            "changed_fields": changed_fields,
            "background": background_result["background"],
            "activated": False,
        },
    )


def derive_palette_action(payload: dict[str, Any]) -> dict[str, Any]:
    theme_id = read_theme_id(payload.get("theme_id"), field_name="theme_id")
    target_path = existing_theme_path(theme_id)
    current_payload = read_theme_payload(target_path, expected_id=theme_id)
    try:
        derived_parameters = derive_theme_palette(
            payload.get("palette"),
            mode=str(current_payload["mode"]),
        )
    except PaletteError as exc:
        raise ToolError("INVALID_PALETTE", str(exc)) from exc

    parameter_paths = {
        parameter: field_path
        for parameter, field_path, _description in THEME_PARAMETER_FIELDS
    }
    next_payload = deepcopy(current_payload)
    changed_fields: list[str] = []
    for parameter, value in derived_parameters.items():
        field_path = parameter_paths.get(parameter)
        if field_path is None:
            raise ToolError(
                "INVALID_PALETTE_CONTRACT",
                "配色派生结果包含未知主题参数。",
                {"parameter": parameter},
            )
        apply_field_update(next_payload, field_path, value)
        changed_fields.append(field_path)

    validate_theme_payload(next_payload, expected_id=theme_id)
    write_theme_payload(target_path, next_payload)
    saved = read_theme_payload(target_path, expected_id=theme_id)
    return success(
        f"已从四个基础色派生并应用主题配色：{saved['name']}（{theme_id}）。",
        {
            "action": "derive_palette",
            "theme_id": theme_id,
            "theme_name": saved["name"],
            "mode": saved["mode"],
            "theme_package_path": str(theme_package_path(theme_id)),
            "theme_file_path": str(target_path),
            "palette": {
                "background": derived_parameters["surface_base"],
                "panel": derived_parameters["surface_panel"],
                "text": derived_parameters["text_primary"],
                "accent": derived_parameters["accent_base"],
            },
            "derived_token_count": len(derived_parameters),
            "changed_fields": changed_fields,
            "background_preserved": True,
        },
    )


def edit_theme(payload: dict[str, Any]) -> dict[str, Any]:
    theme_id = read_theme_id(payload.get("theme_id"), field_name="theme_id")
    target_path = existing_theme_path(theme_id)
    current_payload = read_theme_payload(target_path, expected_id=theme_id)
    next_payload = deepcopy(current_payload)
    changed_fields: list[str] = []

    if "theme_name" in payload and payload.get("theme_name") is not None:
        next_payload["name"] = read_non_empty_string(payload.get("theme_name"), field_name="theme_name")
        changed_fields.append("name")

    updates = read_updates(payload.get("updates"))
    for field_path, value in updates.items():
        apply_field_update(next_payload, field_path, value)
        changed_fields.append(field_path)

    parameter_updates = read_theme_parameter_updates(payload)
    for field_path, value in parameter_updates.items():
        if field_path in updates:
            raise ToolError(
                "DUPLICATE_FIELD_UPDATE",
                "同一个主题字段不能同时通过 updates 和独立参数修改。",
                {"field_path": field_path},
            )
        apply_field_update(next_payload, field_path, value)
        changed_fields.append(field_path)

    background_result = apply_background_updates(next_payload, payload, theme_id)
    changed_fields.extend(background_result["changed_fields"])

    if not changed_fields:
        raise ToolError("NO_CHANGES", "edit 需要提供 theme_name、主题参数、updates 或背景图参数。")

    validate_theme_payload(next_payload, expected_id=theme_id)
    if next_payload.get("id") != current_payload.get("id"):
        raise ToolError("ID_CHANGE_NOT_ALLOWED", "编辑主题不允许修改 theme id。")

    write_theme_payload(target_path, next_payload)
    saved = read_theme_payload(target_path, expected_id=theme_id)
    return success(
        f"已编辑主题 {saved['name']}（{theme_id}）。",
        {
            "action": "edit",
            "theme_id": theme_id,
            "theme_name": saved["name"],
            "theme_package_path": str(theme_package_path(theme_id)),
            "theme_file_path": str(target_path),
            "changed_fields": changed_fields,
            "background": background_result["background"],
        },
    )


def switch_theme(payload: dict[str, Any]) -> dict[str, Any]:
    theme_id = read_theme_id(payload.get("theme_id"), field_name="theme_id")
    target_path = existing_theme_path(theme_id)
    read_theme_payload(target_path, expected_id=theme_id)
    active_theme = set_active_theme(theme_id)
    return success(
        f"已切换当前主题为 {active_theme.name}（{active_theme.id}）。",
        {
            "action": "switch",
            "theme_id": active_theme.id,
            "theme_name": active_theme.name,
            "theme_package_path": str(theme_package_path(theme_id)),
            "theme_file_path": str(target_path),
            "activated": True,
        },
    )


def restore_themes(payload: dict[str, Any]) -> dict[str, Any]:
    restore_ids = read_restore_theme_ids(payload.get("restore_theme_ids"))
    restored: list[dict[str, str]] = []
    active_theme_id = get_theme_settings_repository().get_active_theme_id()

    for theme_id in restore_ids:
        backup_path = backup_theme_path(theme_id)
        backup_payload = read_theme_payload(backup_path, expected_id=theme_id)
        target_path = theme_file_path(theme_id)
        copy_theme_file(backup_path, target_path)
        read_theme_payload(target_path, expected_id=theme_id)
        restored.append(
            {
                "theme_id": theme_id,
                "theme_name": str(backup_payload["name"]),
                "theme_package_path": str(theme_package_path(theme_id)),
                "theme_file_path": str(target_path),
                "backup_file_path": str(backup_path),
            }
        )

    if active_theme_id in restore_ids:
        get_theme(active_theme_id)

    return success(
        f"已恢复 {len(restored)} 个内置主题备份。",
        {
            "action": "restore",
            "restored": restored,
            "activated": False,
            "active_theme_id": active_theme_id,
        },
    )


def delete_theme(payload: dict[str, Any]) -> dict[str, Any]:
    theme_id = read_theme_id(payload.get("theme_id"), field_name="theme_id")
    active_theme_id = get_theme_settings_repository().get_active_theme_id()
    if theme_id == active_theme_id:
        raise ToolError(
            "DELETE_ACTIVE_THEME_NOT_ALLOWED",
            "不能删除当前正在使用的主题；请先切换到其他主题。",
            {"theme_id": theme_id},
        )

    target_path = existing_theme_path(theme_id)
    theme_payload = read_theme_payload(target_path, expected_id=theme_id)
    theme_name = str(theme_payload["name"])
    package_path = theme_package_path(theme_id).resolve()
    theme_root = get_settings().themes_data_path.resolve()
    try:
        package_path.relative_to(theme_root)
    except ValueError as exc:
        raise ToolError(
            "DELETE_THEME_FAILED",
            "主题包路径不在主题目录内，已拒绝删除。",
            {"theme_package_path": str(package_path)},
        ) from exc

    try:
        shutil.rmtree(package_path)
    except OSError as exc:
        raise ToolError(
            "DELETE_THEME_FAILED",
            "无法删除主题包目录。",
            {"theme_package_path": str(package_path), "error": str(exc)},
        ) from exc

    return success(
        f"已删除主题 {theme_name}（{theme_id}）。",
        {
            "action": "delete",
            "theme_id": theme_id,
            "theme_name": theme_name,
            "theme_package_path": str(package_path),
            "theme_file_path": str(target_path),
        },
    )


def read_action(value: Any) -> str:
    action = str(value or "").strip()
    if action not in {
        "list",
        "get_current",
        "create",
        "clone",
        "derive_palette",
        "edit",
        "switch",
        "restore",
        "delete",
    }:
        raise ToolError(
            "INVALID_ARGUMENT",
            "action 必须是 list、get_current、create、clone、derive_palette、edit、switch、restore 或 delete。",
        )
    return action


def read_theme_id(value: Any, *, field_name: str) -> str:
    theme_id = str(value or "").strip()
    if not THEME_ID_PATTERN.fullmatch(theme_id):
        raise ToolError(
            "INVALID_THEME_ID",
            f"{field_name} 必须是小写字母、数字和短横线。",
            {field_name: theme_id},
        )
    return theme_id


def read_optional_theme_id(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return read_theme_id(value, field_name="source_theme_id")


def read_non_empty_string(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 不能为空。")
    return text


def read_theme_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode not in {"dark", "light"}:
        raise ToolError(
            "INVALID_ARGUMENT",
            "theme_mode 必须是 dark 或 light。它只用于浏览器和编辑器兼容，不代表只能有两种主题。",
            {"theme_mode": mode},
        )
    return mode


def read_theme_parameter_updates(payload: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for parameter, field_path, _description in THEME_PARAMETER_FIELDS:
        if parameter not in payload or payload.get(parameter) is None:
            continue
        updates[field_path] = read_non_empty_string(payload.get(parameter), field_name=parameter)
    for parameter, field_path, _description in THEME_BOOLEAN_PARAMETER_FIELDS:
        if parameter not in payload or payload.get(parameter) is None:
            continue
        updates[field_path] = read_optional_bool(payload.get(parameter), field_name=parameter)
    for parameter, field_path, _description, min_value, max_value in THEME_INTEGER_PARAMETER_FIELDS:
        if parameter not in payload or payload.get(parameter) is None:
            continue
        updates[field_path] = read_optional_int(payload.get(parameter), min_value, max_value, parameter)
    return updates


def build_theme_payload_from_parameters(
    theme_id: str,
    theme_name: str,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    missing_parameters = [
        parameter
        for parameter, _field_path, _description in THEME_PARAMETER_FIELDS
        if parameter not in raw_payload or raw_payload.get(parameter) in (None, "")
    ]
    missing_parameters.extend(
        parameter
        for parameter, _field_path, _description in THEME_BOOLEAN_PARAMETER_FIELDS
        if parameter not in raw_payload or raw_payload.get(parameter) is None
    )
    missing_parameters.extend(
        parameter
        for parameter, _field_path, _description, _min_value, _max_value in THEME_INTEGER_PARAMETER_FIELDS
        if parameter not in raw_payload or raw_payload.get(parameter) is None
    )
    if raw_payload.get("theme_mode") in (None, ""):
        missing_parameters.insert(0, "theme_mode")
    if missing_parameters:
        raise ToolError(
            "MISSING_THEME_PARAMETERS",
            "create 需要直接提供完整主题参数，不能再复制旧主题当底稿。",
            {"missing_parameters": missing_parameters},
        )

    next_payload: dict[str, Any] = {
        "schemaVersion": 2,
        "id": theme_id,
        "name": theme_name,
        "mode": read_theme_mode(raw_payload.get("theme_mode")),
        "tokens": {},
        "integrations": {},
    }
    for parameter, field_path, _description in THEME_PARAMETER_FIELDS:
        set_field_value(
            next_payload,
            field_path,
            read_non_empty_string(raw_payload.get(parameter), field_name=parameter),
        )
    for parameter, field_path, _description in THEME_BOOLEAN_PARAMETER_FIELDS:
        set_field_value(
            next_payload,
            field_path,
            read_optional_bool(raw_payload.get(parameter), field_name=parameter),
        )
    for parameter, field_path, _description, min_value, max_value in THEME_INTEGER_PARAMETER_FIELDS:
        set_field_value(
            next_payload,
            field_path,
            read_optional_int(raw_payload.get(parameter), min_value, max_value, parameter),
        )
    set_field_value(next_payload, "tokens.background.image", "")
    set_field_value(next_payload, "tokens.background.opacity", 0)
    set_field_value(next_payload, "tokens.background.blur", 0)
    set_field_value(next_payload, "tokens.background.overlay", "transparent")
    set_field_value(next_payload, "tokens.background.position", "center")
    set_field_value(next_payload, "tokens.background.size", "cover")
    set_field_value(next_payload, "tokens.background.repeat", "no-repeat")
    return next_payload


def set_field_value(payload: dict[str, Any], field_path: str, value: Any) -> None:
    current = payload
    parts = field_path.split(".")
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            raise ToolError("INVALID_THEME_CONTRACT", "主题字段路径无法写入。", {"field_path": field_path})
        current = next_value
    current[parts[-1]] = value


def read_updates(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ToolError("INVALID_ARGUMENT", "updates 必须是对象。")

    updates: dict[str, Any] = {}
    for raw_path, raw_value in value.items():
        field_path = str(raw_path or "").strip()
        if not field_path:
            raise ToolError("INVALID_FIELD_PATH", "updates 包含空字段路径。")
        if not isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            raise ToolError("INVALID_FIELD_VALUE", "主题字段值必须是字符串、数字或布尔值。", {"field_path": field_path})
        updates[field_path] = raw_value.strip() if isinstance(raw_value, str) else raw_value
    return updates


def apply_background_updates(
    payload: dict[str, Any],
    raw_payload: dict[str, Any],
    theme_id: str,
    *,
    package_path: Path | None = None,
) -> dict[str, Any]:
    changed_fields: list[str] = []
    background = ensure_background_tokens(payload)
    copied_asset: dict[str, str] | None = None
    clear_background_image = read_optional_bool(
        raw_payload.get("clear_background_image"),
        field_name="clear_background_image",
    )

    if clear_background_image and raw_payload.get("background_image_path") not in (None, ""):
        raise ToolError("INVALID_ARGUMENT", "clear_background_image 和 background_image_path 不能同时提供。")

    if clear_background_image:
        background["image"] = ""
        changed_fields.append("tokens.background.image")

    if raw_payload.get("background_image_path") not in (None, ""):
        source_path = resolve_source_image_path(raw_payload.get("background_image_path"))
        target_path = copy_background_image_asset(
            source_path,
            theme_id,
            package_path=package_path,
        )
        background["image"] = theme_relative_path(
            theme_id,
            target_path,
            package_path=package_path,
        )
        changed_fields.append("tokens.background.image")
        copied_asset = {
            "source_file_path": str(source_path),
            "asset_file_path": str(target_path),
            "theme_image_value": str(background["image"]),
        }

    scalar_updates = {
        "background_opacity": ("opacity", read_optional_float(raw_payload.get("background_opacity"), 0, 1, "background_opacity")),
        "background_blur": ("blur", read_optional_int(raw_payload.get("background_blur"), 0, 80, "background_blur")),
        "background_overlay": ("overlay", read_optional_string(raw_payload.get("background_overlay"), "background_overlay")),
        "background_position": ("position", read_optional_string(raw_payload.get("background_position"), "background_position")),
        "background_size": ("size", read_optional_string(raw_payload.get("background_size"), "background_size")),
        "background_repeat": ("repeat", read_optional_background_repeat(raw_payload.get("background_repeat"))),
    }
    for raw_field, (token_field, value) in scalar_updates.items():
        if value is None:
            continue
        background[token_field] = value
        changed_fields.append(f"tokens.background.{token_field}")

    return {
        "changed_fields": changed_fields,
        "background": {
            "image": background.get("image", ""),
            "opacity": background.get("opacity", 0),
            "blur": background.get("blur", 0),
            "overlay": background.get("overlay", "transparent"),
            "position": background.get("position", "center"),
            "size": background.get("size", "cover"),
            "repeat": background.get("repeat", "no-repeat"),
            "copied_asset": copied_asset,
        },
    }


def ensure_background_tokens(payload: dict[str, Any]) -> dict[str, Any]:
    tokens = payload.setdefault("tokens", {})
    if not isinstance(tokens, dict):
        raise ToolError("INVALID_THEME_CONTRACT", "主题 tokens 必须是对象。")
    background = tokens.setdefault("background", {})
    if not isinstance(background, dict):
        raise ToolError("INVALID_THEME_CONTRACT", "主题 tokens.background 必须是对象。")
    return background


def read_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 不能为空字符串。")
    return text


def read_optional_float(value: Any, min_value: float, max_value: float, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是数字。")
    number = float(value)
    if number < min_value or number > max_value:
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须在 {min_value} 到 {max_value} 之间。")
    return number


def read_optional_int(value: Any, min_value: int, max_value: int, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是整数。")
    if value < min_value or value > max_value:
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须在 {min_value} 到 {max_value} 之间。")
    return value


def read_optional_bool(value: Any, *, field_name: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是布尔值。")
    return value


def read_optional_background_repeat(value: Any) -> str | None:
    text = read_optional_string(value, "background_repeat")
    if text is None:
        return None
    if text not in {"no-repeat", "repeat", "repeat-x", "repeat-y"}:
        raise ToolError(
            "INVALID_ARGUMENT",
            "background_repeat 必须是 no-repeat、repeat、repeat-x 或 repeat-y。",
            {"background_repeat": text},
        )
    return text


def resolve_source_image_path(value: Any) -> Path:
    raw_path = read_non_empty_string(value, field_name="background_image_path")
    if re.match(r"^[a-z][a-z0-9+.-]*://", raw_path, flags=re.IGNORECASE):
        raise ToolError("INVALID_IMAGE_PATH", "background_image_path 只支持本地图片文件路径。")

    source = Path(raw_path).expanduser()
    candidates = [source] if source.is_absolute() else [Path.cwd() / source, project_root() / source]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            suffix = resolved.suffix.lower()
            if suffix not in BACKGROUND_IMAGE_EXTENSIONS:
                raise ToolError(
                    "INVALID_IMAGE_TYPE",
                    "背景图只支持 avif、gif、jpeg、jpg、png、webp。",
                    {"background_image_path": str(resolved)},
                )
            return resolved
    raise ToolError("IMAGE_NOT_FOUND", "背景图片文件不存在。", {"background_image_path": raw_path})


def copy_background_image_asset(
    source_path: Path,
    theme_id: str,
    *,
    package_path: Path | None = None,
) -> Path:
    assets_dir = (package_path or theme_package_path(theme_id)) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    resolved_assets_dir = assets_dir.resolve()
    resolved_source = source_path.resolve()
    if is_relative_to(resolved_source, resolved_assets_dir):
        return source_path

    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:10]
    safe_stem = sanitize_asset_name(source_path.stem)
    target_path = assets_dir / f"{safe_stem}-{digest}{source_path.suffix.lower()}"

    if resolved_source == target_path.resolve():
        return target_path
    if not target_path.exists():
        temp_path = target_path.with_name(f".{target_path.name}.tmp")
        try:
            shutil.copyfile(source_path, temp_path)
            os.replace(temp_path, target_path)
        except OSError as exc:
            raise ToolError(
                "COPY_IMAGE_FAILED",
                "无法复制背景图片到主题资源目录。",
                {
                    "source_file_path": str(source_path),
                    "asset_file_path": str(target_path),
                    "error": str(exc),
                },
            ) from exc
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
    return target_path


def theme_relative_path(
    theme_id: str,
    path: Path,
    *,
    package_path: Path | None = None,
) -> str:
    package_root = (package_path or theme_package_path(theme_id)).resolve()
    try:
        return path.resolve().relative_to(package_root).as_posix()
    except ValueError as exc:
        raise ToolError(
            "INVALID_THEME_ASSET",
            "主题资源文件必须位于当前主题包目录内。",
            {"theme_id": theme_id, "asset_file_path": str(path)},
        ) from exc


def count_theme_asset_files(package_path: Path) -> int:
    assets_path = package_path / "assets"
    if not assets_path.is_dir():
        return 0
    return sum(1 for path in assets_path.rglob("*") if path.is_file())


def sanitize_asset_name(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return text or "background"


def read_restore_theme_ids(value: Any) -> list[str]:
    if value is None or value == []:
        return list(RESTORABLE_THEME_IDS)
    if not isinstance(value, list):
        raise ToolError("INVALID_ARGUMENT", "restore_theme_ids 必须是数组。")

    result: list[str] = []
    for item in value:
        theme_id = str(item or "").strip()
        if theme_id not in RESTORABLE_THEME_IDS:
            raise ToolError(
                "INVALID_RESTORE_THEME",
                "只能恢复工具内置的 dark-gold 和 light 主题备份。",
                {"theme_id": theme_id},
            )
        if theme_id not in result:
            result.append(theme_id)
    return result or list(RESTORABLE_THEME_IDS)


def apply_field_update(payload: dict[str, Any], field_path: str, value: str) -> None:
    parts = field_path.split(".")
    if len(parts) < 2 or parts[0] not in {"tokens", "integrations"}:
        raise ToolError(
            "FIELD_NOT_ALLOWED",
            "updates 只能修改 tokens.* 或 integrations.* 下已有字段；主题名称请使用 theme_name。",
            {"field_path": field_path},
        )
    if len(parts) >= 2 and parts[0] == "tokens" and parts[1] == "background":
        raise ToolError(
            "FIELD_NOT_ALLOWED",
            "背景图请使用 background_image_path、background_opacity 等专用参数。",
            {"field_path": field_path},
        )
    if any(not FIELD_PART_PATTERN.fullmatch(part) for part in parts):
        raise ToolError("INVALID_FIELD_PATH", "字段路径格式无效。", {"field_path": field_path})

    current: Any = payload
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ToolError("FIELD_NOT_FOUND", "字段路径不存在。", {"field_path": field_path})
        current = current[part]

    leaf = parts[-1]
    if not isinstance(current, dict) or leaf not in current:
        raise ToolError("FIELD_NOT_FOUND", "字段路径不存在。", {"field_path": field_path})
    if isinstance(current[leaf], (dict, list)):
        raise ToolError("FIELD_NOT_SCALAR", "只能修改标量字段，不能替换对象或数组。", {"field_path": field_path})
    current[leaf] = value


def read_theme_payload(path: Path, *, expected_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise ToolError("THEME_NOT_FOUND", "主题文件不存在。", {"theme_file_path": str(path)})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError("INVALID_THEME_JSON", "主题文件不是合法 JSON。", {"theme_file_path": str(path), "error": str(exc)}) from exc
    except OSError as exc:
        raise ToolError("READ_THEME_FAILED", "无法读取主题文件。", {"theme_file_path": str(path), "error": str(exc)}) from exc
    if not isinstance(payload, dict):
        raise ToolError("INVALID_THEME_CONTRACT", "主题文件根节点必须是对象。", {"theme_file_path": str(path)})
    validate_theme_payload(payload, expected_id=expected_id)
    return payload


def validate_theme_payload(payload: dict[str, Any], *, expected_id: str) -> None:
    try:
        theme = ThemeDefinition.model_validate(payload)
    except Exception as exc:
        raise ToolError("INVALID_THEME_CONTRACT", "主题配置不符合当前主题契约。", {"error": str(exc)}) from exc
    if theme.id != expected_id:
        raise ToolError(
            "THEME_ID_MISMATCH",
            "主题 id 必须等于主题包目录名。",
            {"theme_id": theme.id, "expected_id": expected_id},
        )


def write_theme_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        temp_path.write_text(f"{text}\n", encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        raise ToolError("WRITE_THEME_FAILED", "无法写入主题文件。", {"theme_file_path": str(path), "error": str(exc)}) from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def copy_theme_file(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".{target_path.name}.tmp")
    try:
        temp_path.write_bytes(source_path.read_bytes())
        os.replace(temp_path, target_path)
    except OSError as exc:
        raise ToolError(
            "WRITE_THEME_FAILED",
            "无法恢复主题文件。",
            {
                "source_file_path": str(source_path),
                "theme_file_path": str(target_path),
                "error": str(exc),
            },
        ) from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def existing_theme_path(theme_id: str) -> Path:
    path = theme_file_path(theme_id)
    if not path.is_file():
        raise ToolError("THEME_NOT_FOUND", "主题文件不存在。", {"theme_file_path": str(path)})
    return path


def theme_file_path(theme_id: str) -> Path:
    return theme_package_path(theme_id) / THEME_MANIFEST_FILE


def theme_package_path(theme_id: str) -> Path:
    return get_settings().themes_data_path / theme_id


def backup_theme_path(theme_id: str) -> Path:
    return tool_root() / "assets" / "theme_backups" / f"{theme_id}.json"


def project_root() -> Path:
    return get_settings().themes_data_path.parent.parent


def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    run_tool(run)
