from base64 import b64decode
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from app.services.file_preview import policy
from app.services.file_preview.inspection import inspect_file
from app.services.file_preview.word import W, R, REL, CT, word_chunk


def document(tmp_path, body, extras=None, relations=""):
    path = tmp_path / "document.docx"
    parts = {
        "word/document.xml": f'<w:document xmlns:w="{W[1:-1]}" xmlns:r="{R[1:-1]}"><w:body>{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>',
        "word/_rels/document.xml.rels": f'<Relationships xmlns="{REL[1:-1]}">{relations}</Relationships>',
        "[Content_Types].xml": f'<Types xmlns="{CT[1:-1]}"><Default Extension="xml" ContentType="application/xml"/></Types>',
        **(extras or {}),
    }
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return path


def unpack(result):
    archive = ZipFile(BytesIO(b64decode(result["package_base64"])))
    return archive, ET.fromstring(archive.read("word/document.xml"))


def test_large_document_is_chunked_without_losing_text_or_source_positions(tmp_path):
    paragraphs = [f"段落 {i} 完整内容" for i in range(1700)]
    path = document(tmp_path, "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs))
    before = path.read_bytes()
    result = inspect_file(path)
    assert result["mode"] == "paged"
    assert result["word"]["chunks"] > 100
    assert result["word"]["fingerprint"] == "sha256:" + sha256(before).hexdigest()
    # Check separated chunks, including random access to the final one.
    for index in (0, 5, result["word"]["chunks"] - 1):
        chunk = word_chunk(path, index)
        archive, root = unpack(chunk)
        actual = [e.text for e in root.iter(W + "t")]
        source = [int(key) for key in chunk["locations"]]
        assert actual == [paragraphs[number - 1] for number in source]
        assert len(actual) <= policy.WORD_CHUNK_BLOCKS
        assert sum(part.file_size for part in archive.infolist()) < policy.MAX_WORD_PART_BYTES
    assert path.read_bytes() == before


def test_unused_styles_and_resources_are_not_sent_with_each_chunk(tmp_path):
    styles = '<w:styles xmlns:w="' + W[1:-1] + '"><w:style w:styleId="used"><w:basedOn w:val="base"/></w:style><w:style w:styleId="base"/>'
    styles += "".join(f'<w:style w:styleId="unused{i}"><w:rPr><w:b/></w:rPr></w:style>' for i in range(7000)) + "</w:styles>"
    path = document(tmp_path, '<w:p><w:pPr><w:pStyle w:val="used"/></w:pPr><w:r><w:t>正文</w:t></w:r></w:p>',
        {"word/styles.xml": styles, "word/media/unrelated.bin": b"unrelated"},
        f'<Relationship Id="s" Type="{R[1:-1]}/styles" Target="styles.xml"/><Relationship Id="img" Type="{R[1:-1]}/image" Target="media/unrelated.bin"/>')
    assert inspect_file(path)["mode"] == "paged"
    archive, _ = unpack(word_chunk(path, 0))
    assert "word/media/unrelated.bin" not in archive.namelist()
    root = ET.fromstring(archive.read("word/styles.xml"))
    assert {s.get(W + "styleId") for s in root} == {"used", "base"}


def test_table_chunks_preserve_original_table_row_column_and_paragraph(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "WORD_CHUNK_BLOCKS", 2)
    rows = "".join(f'<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>{i}A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>{i}B</w:t></w:r></w:p></w:tc></w:tr>' for i in range(6))
    path = document(tmp_path, f'<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1200"/></w:tblGrid>{rows}</w:tbl>')
    chunk = word_chunk(path, 2)
    locations = list(chunk["locations"].values())
    assert [loc["paragraphIndex"] for loc in locations] == [9, 10, 11, 12]
    assert [loc["rowIndex"] for loc in locations] == [5, 5, 6, 6]
    assert [loc["columnIndex"] for loc in locations] == [1, 3, 1, 3]
    assert all(loc["tableIndex"] == 1 and loc["cellParagraphIndex"] == 1 for loc in locations)
    _, root = unpack(chunk)
    assert len(root.findall(".//" + W + "tbl")) == 1
    assert len(root.findall(".//" + W + "tr")) == 2


def test_vertical_merges_do_not_split_between_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "WORD_CHUNK_BLOCKS", 1)
    rows = "".join(f'<w:tr><w:tc><w:tcPr><w:vMerge {value}/></w:tcPr><w:p><w:r><w:t>{i}</w:t></w:r></w:p></w:tc></w:tr>'
                   for i, value in enumerate(('w:val="restart"', '', 'w:val="restart"')))
    path = document(tmp_path, f'<w:tbl>{rows}</w:tbl>')
    assert inspect_file(path)["word"]["chunks"] == 2
    _, root = unpack(word_chunk(path, 0))
    assert len(root.findall(".//" + W + "tr")) == 2


def test_formula_markup_and_list_progress_survive_chunking(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "WORD_CHUNK_BLOCKS", 1)
    formula = '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>'
    paragraph = '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr></w:pPr>' + formula + '</w:p>'
    path = document(tmp_path, paragraph * 3)
    chunk = word_chunk(path, 2)
    _, root = unpack(chunk)
    assert len(list(root.iter("{http://schemas.openxmlformats.org/officeDocument/2006/math}f"))) == 1
    assert chunk["locations"]["3"]["numbering"] == {"id": "3", "level": "0", "preceding": 2}


def test_single_pathological_block_still_has_a_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "MAX_WORD_UNIT_NODES", 10)
    path = document(tmp_path, "<w:p>" + "<w:r><w:t>x</w:t></w:r>" * 10 + "</w:p>")
    with pytest.raises(policy.PreviewLimit, match="单个段落"):
        inspect_file(path)


def test_xml_entities_are_rejected_in_shared_style_parts(tmp_path):
    path = document(tmp_path, "<w:p/>", {"word/styles.xml": '<!DOCTYPE x [<!ENTITY x "boom">]><styles>&x;</styles>'},
                    f'<Relationship Id="s" Type="{R[1:-1]}/styles" Target="styles.xml"/>')
    with pytest.raises(ValueError, match="实体"):
        word_chunk(path, 0)


def test_inherited_list_style_keeps_numbering_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "WORD_CHUNK_BLOCKS", 1)
    style = f'<w:styles xmlns:w="{W[1:-1]}"><w:style w:styleId="base"><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr></w:style><w:style w:styleId="list"><w:basedOn w:val="base"/></w:style></w:styles>'
    paragraph = '<w:p><w:pPr><w:pStyle w:val="list"/></w:pPr><w:r><w:t>item</w:t></w:r></w:p>'
    path = document(tmp_path, paragraph * 4, {"word/styles.xml": style},
                    f'<Relationship Id="s" Type="{R[1:-1]}/styles" Target="styles.xml"/>')
    assert word_chunk(path, 3)["locations"]["4"]["numbering"]["preceding"] == 3


def test_only_current_chunk_notes_and_images_are_included(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(policy, "WORD_CHUNK_BLOCKS", 1)
    image = BytesIO()
    Image.new("RGB", (3, 3)).save(image, format="PNG")
    body = '<w:p><w:r><w:footnoteReference w:id="1"/></w:r><w:drawing r:embed="img1"/></w:p><w:p><w:r><w:footnoteReference w:id="2"/></w:r><w:drawing r:embed="img2"/></w:p>'
    notes = f'<w:footnotes xmlns:w="{W[1:-1]}"><w:footnote w:id="1"><w:p><w:r><w:t>one</w:t></w:r></w:p></w:footnote><w:footnote w:id="2"><w:p><w:r><w:t>two</w:t></w:r></w:p></w:footnote></w:footnotes>'
    path = document(tmp_path, body, {"word/media/one.png": image.getvalue(), "word/media/two.png": image.getvalue(), "word/footnotes.xml": notes},
        f'<Relationship Id="img1" Type="{R[1:-1]}/image" Target="media/one.png"/><Relationship Id="img2" Type="{R[1:-1]}/image" Target="media/two.png"/><Relationship Id="fn" Type="{R[1:-1]}/footnotes" Target="footnotes.xml"/>')
    archive, _ = unpack(word_chunk(path, 1))
    assert "word/media/one.png" not in archive.namelist()
    assert "word/media/two.png" in archive.namelist()
    assert b"two" in archive.read("word/footnotes.xml") and b"one" not in archive.read("word/footnotes.xml")


def test_large_photos_use_bounded_preview_images_without_rewriting_source(tmp_path):
    from PIL import Image
    image = BytesIO()
    Image.new("RGB", (4000, 3000), "blue").save(image, format="PNG")
    path = document(tmp_path, '<w:p><w:drawing r:embed="img"/></w:p>', {"word/media/photo.png": image.getvalue()},
        f'<Relationship Id="img" Type="{R[1:-1]}/image" Target="media/photo.png"/>')
    before = path.read_bytes()
    archive, _ = unpack(word_chunk(path, 0))
    relation = ET.fromstring(archive.read("word/_rels/document.xml.rels"))[0]
    resource = "word/" + relation.get("Target")
    with Image.open(BytesIO(archive.read(resource))) as preview:
        assert preview.width <= 1600 and preview.height <= 1600
        assert preview.width / preview.height == 4 / 3
    assert len(archive.read(resource)) <= 384 * 1024
    assert path.read_bytes() == before


def test_word_worker_and_routes_keep_identity_and_reject_stale_versions(tmp_path, monkeypatch):
    import asyncio
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.project import files as projects
    from app.api.routes.tools import tool_folder_files as tools
    from app.services.file_preview.runtime import preview_file
    from app.core.errors import register_exception_handlers
    path = document(tmp_path, '<w:p><w:r><w:t>actual worker</w:t></w:r></w:p>')
    class Request:
        async def is_disconnected(self):
            return False
    result = asyncio.run(preview_file(Request(), path, "word", version=policy.version(path), chunk=0))
    assert result["locations"]["1"]["paragraphIndex"] == 1
    assert result["version"] == policy.version(path)
    calls = []
    class Files:
        def get_file_path(self, *identity, target_path):
            calls.append((identity, target_path))
            return path
    async def preview(request, resolved, operation="inspect", **kwargs):
        assert resolved == path
        return {"operation": operation, **kwargs}
    for module, accessor in ((projects, "get_project_file_service"), (tools, "get_tool_folder_file_service")):
        monkeypatch.setattr(module, accessor, Files)
        monkeypatch.setattr(module, "preview_file", preview)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(projects.router)
    app.include_router(tools.router)
    with TestClient(app) as client:
        for prefix in ("/projects/p", "/tools/categories/c/projects/t"):
            url = prefix + "/files/preview/word"
            args = {"path": "docs/source.docx", "version": policy.version(path), "chunk": 8}
            assert client.get(url, params=args).json()["chunk"] == 8
            assert client.get(url, params={**args, "version": "old"}).status_code == 409
            assert client.get(url, params={**args, "chunk": -1}).status_code == 422
    assert calls[0] == (("p",), "docs/source.docx")
    assert calls[2] == (("c", "t"), "docs/source.docx")
