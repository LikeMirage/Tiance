from __future__ import annotations

import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest


PROGRAM_DIR = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAM_DIR))

from config_loader import AutoParams
from retrieval import (
    SearchHit,
    anchored_literal_search,
    auto_rank,
    exact_search,
    hybrid_rank,
    keyword_search,
    load_page_metadata,
    load_text_block_map,
    prepare_text_map_resolver,
    read_context,
    read_page,
)


def build_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE volume (
            volume_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            total_pages INTEGER NOT NULL
        );
        CREATE TABLE page (
            page_id INTEGER PRIMARY KEY,
            volume_id INTEGER NOT NULL,
            physical_page INTEGER NOT NULL,
            printed_number TEXT
        );
        CREATE TABLE block (
            block_id INTEGER PRIMARY KEY,
            page_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            type TEXT,
            text TEXT
        );
        CREATE INDEX idx_block_page ON block(page_id);
        CREATE VIRTUAL TABLE fts_blocks USING fts5(text, tokenize='trigram');
        """
    )
    connection.execute("INSERT INTO volume VALUES(1,'测试卷.pdf',3)")
    connection.executemany(
        "INSERT INTO page(page_id,volume_id,physical_page,printed_number) VALUES(?,?,?,?)",
        [(1,1,1,"1"),(2,1,2,"2"),(3,1,3,"3")],
    )
    blocks = [
        (101,1,1,"title","机器和工人"),
        (102,1,2,"paragraph","机器应用提高劳动生产率，但在一定条件下会使一部分工人失业。"),
        (201,2,1,"paragraph","工资和利润之间存在复杂关系。"),
        (301,3,1,"paragraph","第三页是用于上下文读取的测试文字。"),
        (302,3,2,"paragraph",""),
    ]
    connection.executemany(
        "INSERT INTO block(block_id,page_id,seq,type,text) VALUES(?,?,?,?,?)",
        blocks,
    )
    # Deliberately do NOT reuse block_id as FTS rowid. This reproduces the real database pitfall.
    for rowid, (_, _, _, _, text) in enumerate(blocks, start=1):
        connection.execute("INSERT INTO fts_blocks(rowid,text) VALUES(?,?)", (rowid, text))
    connection.commit()
    connection.close()


class StructuredDatabaseSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "fixture.db"
        build_fixture(self.database)
        self.meta = load_page_metadata(self.database)
        self.text_map = load_text_block_map(self.database)
        self.eligible = set(self.meta)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_search_survives_fts_rowid_mismatch(self) -> None:
        hits, truncated, warnings = exact_search(
            self.database,
            self.meta,
            self.text_map,
            "机器应用提高劳动生产率",
            eligible_pages=self.eligible,
            block_types=None,
            candidate_cap=100,
        )
        self.assertFalse(truncated)
        self.assertEqual(warnings, [])
        self.assertEqual([hit.page_id for hit in hits], [1])

    def test_keyword_search_uses_explicit_keywords_only(self) -> None:
        hits, truncated, terms, warnings = keyword_search(
            self.database,
            self.meta,
            self.text_map,
            "自然语言问题不应再额外补词",
            ["机器应用", "劳动生产率", "工人失业"],
            eligible_pages=self.eligible,
            block_types=None,
            block_candidate_cap=100,
            page_candidate_cap=20,
        )
        self.assertFalse(truncated)
        self.assertEqual(terms, ("机器应用", "劳动生产率", "工人失业"))
        self.assertEqual(warnings, [])
        self.assertEqual(hits[0].page_id, 1)
        self.assertEqual(hits[0].detail, "关键词覆盖=3/3; 出现次数=3")

    def test_read_page_and_context_keep_order(self) -> None:
        page = read_page(
            self.database,
            page_id=1,
            volume_id=None,
            physical_page=None,
            max_chars=20000,
        )
        self.assertEqual([block["seq"] for block in page["blocks"]], [1, 2])
        context = read_context(
            self.database,
            page_id=2,
            volume_id=None,
            physical_page=None,
            before=1,
            after=1,
            max_chars_per_page=20000,
        )
        self.assertEqual([page["physical_page"] for page in context["pages"]], [1, 2, 3])
        self.assertFalse(context["any_truncated"])

    def test_hybrid_and_auto_exact_gate(self) -> None:
        keyword = [
            SearchHit(page_id=1, score=1.0, detail="kw"),
            SearchHit(page_id=2, score=0.4, detail="kw"),
        ]
        vector = [
            SearchHit(page_id=2, score=1.0, detail="vec"),
            SearchHit(page_id=1, score=0.5, detail="vec"),
        ]
        hybrid = hybrid_rank(keyword, vector, 0.8)
        self.assertEqual(hybrid[0].page_id, 1)

        exact = [SearchHit(page_id=1, score=1.0, detail="exact")]
        auto = auto_rank(
            "机器提高生产率",
            self.meta,
            exact,
            [],
            keyword,
            vector,
            AutoParams(
                bias=0.0,
                length_ratio_coefficient=-1.5,
                lexical_confidence_coefficient=1.5,
                semantic_margin_coefficient=6.0,
            ),
        )
        self.assertEqual(auto[0].page_id, 1)
        self.assertTrue(auto[0].detail.startswith("精确门控"))

    def test_anchor_fallback_recovers_near_literal_variant(self) -> None:
        hits, truncated, anchors = anchored_literal_search(
            self.database,
            self.meta,
            self.text_map,
            "机器应用提高劳动生产率所以会使工人失业",
            eligible_pages=self.eligible,
            block_types=None,
            per_anchor_cap=50,
        )
        self.assertFalse(truncated)
        self.assertTrue(anchors)
        self.assertTrue(hits)
        self.assertEqual(hits[0].page_id, 1)
        self.assertGreaterEqual(hits[0].literal_strength, 2)
        self.assertGreaterEqual(len(hits[0].longest_anchor or ""), 8)

    def test_text_map_sidecar_cache_is_reused(self) -> None:
        cache_root = Path(self.temp.name) / ".Tiance" / "cache"
        first = prepare_text_map_resolver(self.database, cache_root)
        self.assertIsNotNone(first.cache_path)
        self.assertTrue(first.cache_path.is_file())
        refs = first.resolve(["机器和工人"])
        key = next(iter(refs))
        self.assertIn((1, "title"), refs[key])

        second = prepare_text_map_resolver(self.database, cache_root)
        self.assertTrue(second.cache_reused)
        self.assertEqual(second.cache_path, first.cache_path)



if __name__ == "__main__":
    unittest.main()
