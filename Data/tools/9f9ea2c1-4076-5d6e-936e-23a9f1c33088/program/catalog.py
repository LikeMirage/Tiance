"""Read the pinned, offline icon catalog. No host service or network dependency."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
import zipfile

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)


class Catalog:
    def __init__(self, assets: Path = ASSETS):
        self.assets = assets
        self.catalog = json.loads((assets / "catalog.json").read_text(encoding="utf-8"))
        if self.catalog["schema_version"] != 1:
            raise ValueError("Unsupported icon catalog version")
        self.libraries = {item["id"]: item for item in self.catalog["libraries"]}
        self._records = None
        self._by_id = None

    @property
    def records(self) -> list[dict]:
        if self._records is None:
            raw = gzip.decompress((self.assets / self.catalog["index"]).read_bytes())
            if hashlib.sha256(raw).hexdigest() != self.catalog["index_sha256"]:
                raise ValueError("Icon index is damaged; restore assets from the tool package")
            records = json.loads(raw)
            by_id = {item["id"]: item for item in records}
            if len(records) != len(by_id):
                raise ValueError("Duplicate IDs in the icon catalog")
            self._records, self._by_id = records, by_id
        return self._records

    def select(self, ids: list[str]) -> list[dict]:
        _ = self.records
        missing = [icon_id for icon_id in ids if icon_id not in self._by_id]
        if missing:
            raise ValueError("Unknown icon IDs: " + ", ".join(missing) + "; use IDs returned by search")
        return [self._by_id[icon_id] for icon_id in ids]

    def svg(self, record: dict) -> bytes:
        library = self.libraries[record["library"]]
        with zipfile.ZipFile(self.assets / library["archive"]) as archive:
            raw = archive.read(record["path"])
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError(f"SVG integrity check failed: {record['id']}")
        return raw

    def describe(self, record: dict) -> dict:
        library = self.libraries[record["library"]]
        return {key: record[key] for key in ("id", "name", "library", "style")} | {
            "library_name": library["name"], "version": library["version"],
            "license": library["license"],
        }

    def search(self, queries: list[str], libraries: list[str], limit: int, offset: int) -> list[dict]:
        unknown = set(libraries) - self.libraries.keys()
        if unknown:
            raise ValueError("Unknown libraries: " + ", ".join(sorted(unknown)))
        selected = set(libraries)
        candidates = []
        for record in self.records:
            if record["library"] not in selected:
                continue
            name = " ".join(words(record["name"]))
            aliases = [" ".join(words(x)) for x in record["aliases"]]
            tags = " ".join(words(" ".join(record["tags"] + record["categories"])))
            searchable = name + " " + " ".join(aliases) + " " + tags + " " + record["style"]
            candidates.append((record, name, aliases, set(words(searchable)), searchable))
        results = []
        for query in queries:
            tokens = words(query)
            if not tokens:
                raise ValueError("Each query must contain searchable words")
            normalized = " ".join(tokens)
            matches = []
            for record, name, aliases, terms, searchable in candidates:
                if not all(token in searchable for token in tokens):
                    continue
                score = (100 if name == normalized else 90 if normalized in aliases else
                         70 if all(t in words(name) for t in tokens) else
                         50 if all(t in terms for t in tokens) else 20)
                # Prefer the library's regular outline, but keep every variant searchable.
                default_style = record["style"] in {"regular", "outline", "24/outline"}
                matches.append((-score, not default_style, record["name"], record["id"], record))
            matches.sort(key=lambda value: value[:4])
            page = matches[offset:offset + limit]
            results.append({"query": query, "total": len(matches), "offset": offset,
                            "returned": len(page), "has_more": offset + len(page) < len(matches),
                            "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
                            "items": [self.describe(match[-1]) for match in page]})
        return results
