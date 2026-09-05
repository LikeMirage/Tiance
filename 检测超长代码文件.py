# -*- coding: utf-8 -*-
"""扫描前后端与桌面壳源码，列出超过 500 行和超过 1000 行的代码文件，
并把结果同时输出到控制台和保存为一份 Markdown 报告文件。

用法:
    python 检测超长代码文件.py [--threshold N] [--dir DIR ...] [--output PATH]

默认扫描 1_PythonServer、2_ReactWeb、3_PyWebView 三个源码目录，
按代码文件真实行数统计，跳过缓存、构建产物与依赖目录。
报告默认保存到根目录：长代码文件检测报告.md
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "长代码文件检测报告.md"

DEFAULT_DIRS = ("1_PythonServer", "2_ReactWeb", "3_PyWebView")

# 参与统计的代码后缀
CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
    ".vue",
}

# 跳过的目录（名称精确匹配任意层级）
EXCLUDE_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".venv",
    ".vite",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "test-results",
    "vendor",
    "venv",
    "public",
}

# 跳过的文件
EXCLUDE_FILES = {
    "vite.config.js",
    "vite.config.d.ts",
}


def should_skip(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    return path.name in EXCLUDE_FILES


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def iter_code_files(base: Path):
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if should_skip(path):
            continue
        if path.suffix.lower() not in CODE_SUFFIXES:
            continue
        yield path


def group_by_scope(path: Path) -> str:
    """判断文件属于后端、前端还是桌面壳。"""
    for dirname, label in (
        ("1_PythonServer", "后端 1_PythonServer"),
        ("2_ReactWeb", "前端 2_ReactWeb"),
        ("3_PyWebView", "桌面壳 3_PyWebView"),
    ):
        if dirname in path.parts:
            return label
    return "其他"


def build_report(
    threshold: int,
    severe_threshold: int,
    all_files: list[tuple[int, Path]],
    scanned_dirs: tuple[str, ...],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    long_files = [item for item in all_files if item[0] >= threshold]
    huge_files = [item for item in all_files if item[0] >= severe_threshold]

    lines: list[str] = []
    lines.append("# 长代码文件检测报告")
    lines.append("")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- 扫描范围: {', '.join(scanned_dirs)}")
    lines.append(f"- 统计口径: 代码文件真实行数，达到 **{threshold}** 行即列入")
    lines.append(f"- 命中文件数: **{len(all_files)}**")
    lines.append("")

    # 超大文件
    lines.append(f"## 一、超大文件（≥ {severe_threshold} 行，共 {len(huge_files)} 个）")
    lines.append("")
    if huge_files:
        lines.append("| 行数 | 归属 | 文件 |")
        lines.append("| ---: | --- | --- |")
        for num, path in huge_files:
            rel = path.relative_to(ROOT).as_posix()
            lines.append(f"| {num:,} | {group_by_scope(path)} | `{rel}` |")
    else:
        lines.append("（无）")
    lines.append("")

    # 长文件
    lines.append(f"## 二、长文件（≥ {threshold} 行，共 {len(long_files)} 个）")
    lines.append("")
    if long_files:
        lines.append("| 行数 | 归属 | 文件 |")
        lines.append("| ---: | --- | --- |")
        for num, path in long_files:
            rel = path.relative_to(ROOT).as_posix()
            lines.append(f"| {num:,} | {group_by_scope(path)} | `{rel}` |")
    else:
        lines.append("（无）")
    lines.append("")

    # 按归属分布汇总
    lines.append("## 三、分布汇总")
    lines.append("")
    lines.append("| 归属 | ≥ 500 行 | ≥ 1000 行 |")
    lines.append("| --- | ---: | ---: |")
    scope_all: dict[str, int] = {}
    scope_huge: dict[str, int] = {}
    for num, path in all_files:
        scope = group_by_scope(path)
        scope_all[scope] = scope_all.get(scope, 0) + 1
        if num >= severe_threshold:
            scope_huge[scope] = scope_huge.get(scope, 0) + 1
    for scope in ("后端 1_PythonServer", "前端 2_ReactWeb", "桌面壳 3_PyWebView", "其他"):
        lines.append(f"| {scope} | {scope_all.get(scope, 0)} | {scope_huge.get(scope, 0)} |")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="检测超长代码文件")
    parser.add_argument(
        "--threshold",
        type=int,
        default=500,
        help="超过多少行即列入长文件（默认 500）",
    )
    parser.add_argument(
        "--dir",
        action="append",
        default=list(DEFAULT_DIRS),
        help="要扫描的目录（可多次指定，默认扫描前后端+桌面壳）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"报告输出路径（默认 {DEFAULT_OUTPUT.name}）",
    )
    args = parser.parse_args()

    threshold = args.threshold
    severe_threshold = max(1000, threshold)

    all_files: list[tuple[int, Path]] = []

    for dirname in args.dir:
        base = ROOT / dirname
        if not base.exists():
            print(f"[skip] 目录不存在: {dirname}")
            continue
        for path in iter_code_files(base):
            lines = count_lines(path)
            if lines >= threshold:
                all_files.append((lines, path))

    # 行数降序
    all_files.sort(key=lambda item: (-item[0], str(item[1])))

    report = build_report(threshold, severe_threshold, all_files, tuple(args.dir))

    # 写报告
    try:
        args.output.write_text(report, encoding="utf-8")
        print(f"报告已保存: {args.output}")
    except OSError as exc:
        print(f"[warn] 报告写入失败: {exc}")

    # 控制台简略输出
    long_count = sum(1 for num, _ in all_files if num >= threshold)
    huge_count = sum(1 for num, _ in all_files if num >= severe_threshold)
    print("=" * 60)
    print(f"扫描范围: {', '.join(args.dir)} | 命中 {len(all_files)} 个")
    print(f"≥ {threshold} 行: {long_count} 个 | ≥ {severe_threshold} 行: {huge_count} 个")
    print(f"详细报告: {args.output}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
