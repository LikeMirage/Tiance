"""Rebuild pinned offline icon resources. Developer command; never called by the tool."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

PACKAGES = [
    ("phosphor", "Phosphor", "@phosphor-icons/core", "2.1.1", "package/assets/", "https://github.com/phosphor-icons/core"),
    ("lucide", "Lucide", "lucide-static", "1.70.0", "package/icons/", "https://github.com/lucide-icons/lucide"),
    ("tabler", "Tabler", "@tabler/icons", "3.50.0", "package/icons/", "https://github.com/tabler/tabler-icons"),
    ("heroicons", "Heroicons", "heroicons", "2.2.0", "package/", "https://github.com/tailwindlabs/heroicons"),
]
ROOT = Path(__file__).resolve().parents[1]


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def phosphor_metadata(text: str) -> dict:
    # Read the pinned generated catalog as data, without executing JavaScript.
    source = text.split("const n = [", 1)[1].split("];", 1)[0]
    enums = dict(re.findall(r'i\.([A-Z_]+) = ("[^"\n]*")', text.split("const n", 1)[0].split("a =", 1)[0]))
    result = {}
    for block in re.findall(r"\{(.*?)\}", source, re.S):
        name = json.loads(re.search(r'\bname:\s*("[^"\n]+")', block).group(1))
        tags = re.search(r"\btags:\s*(\[.*?\])", block, re.S)
        cats = re.search(r"\bcategories:\s*\[(.*?)\]", block, re.S)
        aliases = re.search(r'\balias:\s*("[^"\n]+")', block)
        result[name] = {
            "tags": json.loads(tags.group(1)) if tags else [],
            "categories": [json.loads(enums[c]) for c in re.findall(r"e\.([A-Z_]+)", cats.group(1))] if cats else [],
            "aliases": [json.loads(aliases.group(1))] if aliases else [],
        }
    if len(result) != 1512:
        raise ValueError("Phosphor catalog format/count changed: review the metadata parser")
    return result


def svg_info(data: bytes) -> tuple[str, list[float]]:
    root = ET.fromstring(data)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Not an SVG document")
    viewbox = [float(x) for x in root.attrib["viewBox"].split()]
    if len(viewbox) != 4 or min(viewbox[2:]) <= 0:
        raise ValueError("Invalid SVG viewBox")
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "image"}:
            raise ValueError("Unexpected active/external SVG content")
        if any(k.lower().startswith("on") or k.rsplit("}", 1)[-1] == "href" for k in node.attrib):
            raise ValueError("Unexpected SVG resource/event attribute")
    return hashlib.sha256(data).hexdigest(), viewbox


def build(cache: Path) -> None:
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "licenses").mkdir(exist_ok=True)
    libraries, records = [], []
    for key, name, package, version, prefix, source in PACKAGES:
        with urllib.request.urlopen(f"https://registry.npmjs.org/{package}/{version}", timeout=45) as response:
            dist = json.load(response)["dist"]
        cached = cache / f"{key}-icons.tgz"
        if cached.is_file():
            raw = cached.read_bytes()
        else:
            with urllib.request.urlopen(dist["tarball"], timeout=60) as response:
                raw = response.read()
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
        if integrity != dist["integrity"]:
            raise ValueError(f"Package integrity mismatch: {package}@{version}")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            def read(path: str) -> bytes:
                return archive.extractfile(path).read()
            metadata = {}
            if key == "phosphor":
                metadata = phosphor_metadata(read("package/dist/index.mjs").decode())
            elif key == "lucide":
                metadata = json.loads(read("package/tags.json"))
            elif key == "tabler":
                metadata = json.loads(read("package/icons.json"))
            license_text = read("package/LICENSE")
            (assets / "licenses" / f"{key}.txt").write_bytes(license_text)
            members = sorted((m for m in archive.getmembers() if m.isfile() and m.name.startswith(prefix) and m.name.endswith(".svg")), key=lambda m: m.name)
            styles, byte_count = set(), 0
            target = assets / f"{key}.zip"
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
                for member in members:
                    relative = member.name.removeprefix(prefix)
                    parts = PurePosixPath(relative).parts
                    stem = PurePosixPath(relative).stem
                    if key == "phosphor":
                        style = parts[0]
                        base = stem.removesuffix("-" + style) if style != "regular" else stem
                        meta = metadata[base]
                    elif key == "tabler":
                        style, base = parts[0], stem
                        item = metadata[base]
                        meta = {"tags": item.get("tags", []), "categories": [item["category"]], "aliases": []}
                    elif key == "lucide":
                        style, base = "outline", stem
                        meta = {"tags": metadata.get(base, []), "categories": [], "aliases": []}
                    else:
                        style, base = "/".join(parts[:-1]), stem
                        meta = {"tags": [], "categories": [], "aliases": []}
                    # Tabler includes numeric tags such as 420 and digits. They are
                    # legitimate search terms, not malformed or discardable data.
                    for field in ("tags", "categories", "aliases"):
                        if any(value is not None and not isinstance(value, (str, int, float)) for value in meta[field]):
                            raise ValueError(f"Unexpected {field} metadata in {key}:{relative}")
                        meta[field] = [value if isinstance(value, str) else json.dumps(value) for value in meta[field]]
                    data = read(member.name)
                    digest, box = svg_info(data)
                    info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    output.writestr(info, data)
                    records.append({"id": f"{key}:{relative[:-4]}", "library": key, "name": base, "style": style, "path": relative, "tags": meta["tags"], "categories": meta["categories"], "aliases": meta["aliases"], "view_box": box, "sha256": digest, "size_bytes": len(data)})
                    styles.add(style)
                    byte_count += len(data)
            libraries.append({"id": key, "name": name, "version": version, "package": package, "source": source, "package_url": dist["tarball"], "package_integrity": integrity, "license_file": f"licenses/{key}.txt", "license": "ISC / MIT (see bundled notice)" if key == "lucide" else "MIT", "styles": sorted(styles), "icon_count": len(members), "svg_bytes": byte_count, "archive": target.name, "archive_bytes": target.stat().st_size, "archive_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
            print(f"{name} {version}: {len(members)} SVGs, {target.stat().st_size} packaged bytes")
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate icon identifiers")
    index = json_bytes(records)
    (assets / "index.json.gz").write_bytes(gzip.compress(index, mtime=0))
    catalog = {"schema_version": 1, "index": "index.json.gz", "index_sha256": hashlib.sha256(index).hexdigest(), "libraries": libraries}
    (assets / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Total {len(records)} SVGs; index {len(index)} bytes, compressed { (assets / 'index.json.gz').stat().st_size} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path.cwd())
    build(parser.parse_args().cache)
