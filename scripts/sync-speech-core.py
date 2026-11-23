"""Keep two independently shipped speech engines byte-identical.

python scripts/sync-speech-core.py --from-tool  (after editing the tool core)
python scripts/sync-speech-core.py --from-backend  (after editing the backend core)
python scripts/sync-speech-core.py --check  (CI / release validation)
Adapters and configuration remain owned by each host.
"""
from pathlib import Path
import argparse
import base64
import csv
import hashlib
import shutil

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'Data/tools/092dcd37-8d51-467d-b607-5a6441dd989a/program'
BACKEND = ROOT / '1_PythonServer/app/services/speech'
MEDIA = Path('vendor/cp313-win_amd64')
FILES = [f'jianying_asr/{name}.py' for name in (
    '__init__', 'client', 'common', 'export', 'media_copy', 'media_runtime',
    'media', 'segmentation', 'parallel', 'engine', 'signing', 'silk',
)] + ['vendor/silk/' + name for name in (
    'windows/silk_v3_decoder.exe', 'LICENSE-MIT.txt', 'LICENSE-Skype.txt', 'source.json',
)]


def media_files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def verified_media_files(root: Path) -> set[Path]:
    records = list(root.glob('av-*+audio.*.dist-info/RECORD'))
    if len(records) != 1:
        raise ValueError(f'Expected one audio-only PyAV wheel in {root}')
    files = media_files(root)
    with records[0].open(encoding='utf-8', newline='') as stream:
        entries = list(csv.reader(stream))
    if files != {Path(name) for name, _, _ in entries}:
        raise ValueError(f'Media files do not match the wheel RECORD in {root}')
    for name, checksum, size in entries:
        path = root / name
        if path == records[0]:
            continue
        content = path.read_bytes()
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
        if checksum != 'sha256=' + digest or len(content) != int(size):
            raise ValueError(f'Invalid wheel file: {path}')
    return files


def sync_core(source: Path, target: Path, *, check: bool) -> None:
    media = verified_media_files(source / MEDIA)
    extra = media_files(target / MEDIA) - media
    different = []
    for relative in [*map(Path, FILES), *(MEDIA / p for p in sorted(media))]:
        src, dst = source / relative, target / relative
        if dst.is_file() and src.read_bytes() == dst.read_bytes():
            continue
        if check:
            different.append(str(relative))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    if check and (extra or different):
        raise ValueError('Speech core differs: ' + ', '.join(different + [str(MEDIA / p) for p in sorted(extra)]))
    for relative in extra:
        path = target / MEDIA / relative
        if not path.resolve().is_relative_to((target / MEDIA).resolve()):
            raise ValueError(f'Unexpected media file location: {path}')
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for flag in ('check', 'from-tool', 'from-backend'):
        group.add_argument('--' + flag, action='store_true')
    args = parser.parse_args()
    source, target = (BACKEND, TOOL) if args.from_backend else (TOOL, BACKEND)
    try:
        sync_core(source, target, check=args.check)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.check:
        packages = ROOT / 'runtime/python-packages/backend/py313/site-packages'
        if any((packages / p).exists() for p in ('av', 'av.libs')) or any(packages.glob('av-*.dist-info')):
            raise SystemExit('Redundant PyAV installation in the packaged backend site-packages.')
    print('Speech engines, SILK and audio-only PyAV match.')


if __name__ == '__main__':
    main()
