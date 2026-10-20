"""Bounded, read-only CSV/TSV projections in the disposable preview worker."""
import codecs
import csv
from pathlib import Path

from . import policy

ENCODINGS = {"auto", "utf-8-sig", "gb18030", "utf-16"}
DELIMITERS = {"comma": ",", "tab": "\t", "semicolon": ";", "pipe": "|"}


def _format(path: Path, encoding: str, delimiter: str) -> tuple[str, str]:
    if encoding not in ENCODINGS or delimiter not in {"auto", *DELIMITERS}:
        raise ValueError("不支持的文本编码或分隔符。")
    if path.stat().st_size > policy.MAX_DELIMITED_BYTES:
        raise policy.PreviewLimit("CSV/TSV 超过 256 MiB 内置预览预算，请用默认应用查看。")
    with path.open("rb") as source:
        sample = source.read(65536)
    if encoding == "auto":
        if sample.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            raise ValueError("暂不支持 UTF-32，请另存为 UTF-8 或 UTF-16。")
        if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        else:
            try:
                codecs.getincrementaldecoder("utf-8-sig")().decode(sample, final=False)
                encoding = "utf-8-sig"
            except UnicodeDecodeError:
                encoding = "gb18030"
    try:
        text = codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
    except UnicodeError as error:
        raise ValueError("无法按所选编码读取，请切换文本编码。") from error
    if delimiter == "auto":
        if path.suffix.lower() == ".tsv":
            delimiter = "tab"
        else:
            # Sniff only complete logical records; a sample can end in a quoted field.
            complete = _sample_records(text)
            try:
                char = csv.Sniffer().sniff(complete, delimiters=",;\t|").delimiter
                delimiter = next(key for key, value in DELIMITERS.items() if value == char)
            except csv.Error:
                delimiter = "comma"
    return encoding, delimiter


def _sample_records(text: str) -> str:
    quoted = False
    end = 0
    for index, char in enumerate(text):
        if char == '"':
            quoted = not quoted
        elif char in "\r\n" and not quoted:
            end = index + 1
    return text[:end] if end else text


def _rows(path: Path, encoding: str, delimiter: str):
    # Bound the physical line AND the whole logical record before csv.reader
    # allocates cells, including multiline fields and millions of tiny columns.
    record_chars = 0
    total_chars = 0
    csv.field_size_limit(policy.MAX_DELIMITED_RECORD_CHARS)
    with path.open("r", encoding=encoding, errors="strict", newline="") as source:
        def lines():
            nonlocal record_chars, total_chars
            while True:
                line = source.readline(policy.MAX_DELIMITED_RECORD_CHARS + 1)
                if not line:
                    return
                record_chars += len(line)
                total_chars += len(line)
                if record_chars > policy.MAX_DELIMITED_RECORD_CHARS:
                    raise policy.PreviewLimit("CSV/TSV 单条记录超过 100 万字符，请用默认应用查看。")
                if total_chars > policy.MAX_DELIMITED_BYTES:
                    raise policy.PreviewLimit("CSV/TSV 实际读取内容超过预览预算。")
                if "\0" in line:
                    raise ValueError("文本中含有空字符，请检查编码或文件格式。")
                yield line
        try:
            for index, row in enumerate(csv.reader(lines(), delimiter=DELIMITERS[delimiter], strict=True)):
                record_chars = 0
                if index >= policy.MAX_DELIMITED_ROWS or len(row) > policy.MAX_DELIMITED_COLUMNS:
                    raise policy.PreviewLimit("CSV/TSV 超过 1048576 行或 16384 列预览预算。")
                yield row
        except UnicodeError as error:
            raise ValueError("文件中包含当前编码无法读取的内容，请切换文本编码。") from error
        except csv.Error as error:
            raise ValueError(f"CSV/TSV 格式解析失败，请检查引号或切换分隔符：{error}") from error


def inspect_delimited(path: Path, encoding: str = "auto", delimiter: str = "auto") -> dict:
    encoding, delimiter = _format(path, encoding, delimiter)
    rows = columns = 0
    for row in _rows(path, encoding, delimiter):
        rows += 1
        columns = max(columns, len(row))
    return {
        "mode": "paged", "size_bytes": path.stat().st_size,
        "sheets": [{"name": path.name, "rows": rows, "columns": columns}],
        "page_rows": policy.PAGE_ROWS, "page_columns": policy.PAGE_COLUMNS,
        "delimited": {"encoding": encoding, "delimiter": delimiter},
    }


def delimited_page(path: Path, sheet: int, row_start: int, column_start: int,
                   encoding: str = "auto", delimiter: str = "auto") -> dict:
    if sheet != 0 or not 0 <= row_start < policy.MAX_DELIMITED_ROWS or not 0 <= column_start < policy.MAX_DELIMITED_COLUMNS:
        raise ValueError("表格分页坐标无效。")
    encoding, delimiter = _format(path, encoding, delimiter)
    values = []
    text_chars = 0
    records = _rows(path, encoding, delimiter)
    try:
        for index, row in enumerate(records):
            if index < row_start:
                continue
            cells = row[column_start:column_start + policy.PAGE_COLUMNS]
            text_chars += sum(map(len, cells))
            if text_chars > policy.MIB:
                raise policy.PreviewLimit("本页单元格文本超过 100 万字符，请用默认应用查看。")
            values.append(cells + [""] * (policy.PAGE_COLUMNS - len(cells)))
            if len(values) >= policy.PAGE_ROWS:
                break
    finally:
        records.close()
    return {"sheet_name": path.name, "row_start": row_start, "column_start": column_start, "values": values}
