from __future__ import annotations

import os
from pathlib import Path
from tempfile import mkstemp

from docx import Document

from app.core.atomic_replace import atomic_replace_path

from .docx_package_postprocess import postprocess_docx_package
from .docx_package_validation import validate_docx_package


def save_document_atomically(
    document: Document,
    output_path: Path,
    *,
    footnotes: list[tuple[int, str]],
    endnotes: list[tuple[int, str]],
    update_fields: bool,
    overwrite: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise ValueError("目标文件已存在；如需覆盖请设置 overwrite=true。")
    descriptor, temp_name = mkstemp(
        prefix=f".{output_path.stem}-",
        suffix=".docx.tmp",
        dir=str(output_path.parent),
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        document.save(str(temp_path))
        postprocess_docx_package(
            temp_path,
            footnotes=footnotes,
            endnotes=endnotes,
            update_fields=update_fields,
        )
        validate_docx_package(temp_path)
        _commit_temp_file(temp_path, output_path, overwrite=overwrite)
    finally:
        temp_path.unlink(missing_ok=True)


def _commit_temp_file(temp_path: Path, output_path: Path, *, overwrite: bool) -> None:
    if overwrite:
        atomic_replace_path(temp_path, output_path)
        return
    try:
        os.link(temp_path, output_path)
    except FileExistsError as exc:
        raise ValueError("目标文件已存在；如需覆盖请设置 overwrite=true。") from exc
    temp_path.unlink()
