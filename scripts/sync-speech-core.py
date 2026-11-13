"""Keep two independently shipped speech engines byte-identical.

python scripts/sync-speech-core.py --from-tool  (after editing the tool core)
python scripts/sync-speech-core.py --from-backend  (after editing the backend core)
python scripts/sync-speech-core.py --check  (CI / release validation)
Adapters, configuration and dependency installation remain owned by each host.
"""
from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'Data/tools/092dcd37-8d51-467d-b607-5a6441dd989a/program'
BACKEND = ROOT / '1_PythonServer/app/services/speech'
FILES = [f'jianying_asr/{name}.py' for name in (
    '__init__', 'client', 'common', 'export', 'media_copy', 'media_runtime',
    'media', 'parallel', 'engine', 'signing', 'silk',
)] + ['vendor/silk/' + name for name in (
    'windows/silk_v3_decoder.exe', 'LICENSE-MIT.txt', 'LICENSE-Skype.txt', 'source.json',
)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for flag in ('check', 'from-tool', 'from-backend'):
        group.add_argument('--' + flag, action='store_true')
    args = parser.parse_args()
    if args.check:
        different = [p for p in FILES if not (TOOL / p).is_file()
                     or not (BACKEND / p).is_file()
                     or (TOOL / p).read_bytes() != (BACKEND / p).read_bytes()]
        if different:
            raise SystemExit('Speech core differs: ' + ', '.join(different))
        print('Speech core copies match.')
        return
    source, target = (TOOL, BACKEND) if args.from_tool else (BACKEND, TOOL)
    for relative in FILES:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
    print(f'Synchronized {len(FILES)} speech core files.')


if __name__ == '__main__':
    main()
