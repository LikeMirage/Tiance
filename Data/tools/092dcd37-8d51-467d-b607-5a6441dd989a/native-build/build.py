import json
import os
import subprocess
import sys
import shutil
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: python native-build/build.py <prepared-build-directory>")
ROOT = Path(sys.argv[1]).resolve()
CONFIG = Path(__file__).resolve().parent
COMPILER = ROOT / "compiler/llvm-mingw-20261104-ucrt-x86_64/bin"
MAKE = ROOT / "make/usr/bin/make.exe"
BASH = Path("C:/Program Files/Git/usr/bin/bash.exe")
PREFIX = ROOT / "ffmpeg-install"
SOURCE = ROOT / "sources/ffmpeg-8.0.1"
BUILD = ROOT / "ffmpeg-build"
BUILD.mkdir(exist_ok=True)
env = os.environ.copy()
env["PATH"] = os.pathsep.join([str(COMPILER), str(ROOT / "nasm/nasm-2.16.03"),
                               str(MAKE.parent), str(BASH.parent), env["PATH"]])
env["LC_ALL"] = "C"

def run(command, cwd, log):
    print("Running:", subprocess.list2cmdline([str(p) for p in command]), flush=True)
    with (ROOT / log).open("w", encoding="utf-8") as stream:
        done = subprocess.run([str(p) for p in command], cwd=cwd, env=env,
                              stdout=stream, stderr=subprocess.STDOUT)
    if done.returncode:
        print((ROOT / log).read_text(encoding="utf-8", errors="replace")[-12000:])
        raise SystemExit(done.returncode)

decoders = json.loads((CONFIG / "audio-decoders.json").read_text())
aliases = {"8svx_exp": "eightsvx_exp", "8svx_fib": "eightsvx_fib", "acelp.kelvin": "acelp_kelvin",
           "atrac3plus": "atrac3p", "atrac3plusal": "atrac3pal", "g722": "adpcm_g722",
           "g726": "adpcm_g726", "g726le": "adpcm_g726le", "interplayacm": "interplay_acm",
           "real_144": "ra_144", "real_288": "ra_288", "wavesynth": "ffwavesynth"}
decoders = [aliases.get(name, name) for name in decoders]
zlib = ROOT / "sources/zlib-1.3.1"
if not (PREFIX / "lib/libz.a").exists():
    run([MAKE, "-f", "win32/Makefile.gcc", "-j4", "CC=x86_64-w64-mingw32-clang",
         "AR=llvm-ar", "libz.a"], zlib, "zlib-compile.log")
    (PREFIX / "lib").mkdir(parents=True, exist_ok=True)
    (PREFIX / "include").mkdir(parents=True, exist_ok=True)
    shutil.copy2(zlib / "libz.a", PREFIX / "lib/libz.a")
    for name in ("zlib.h", "zconf.h"):
        shutil.copy2(zlib / name, PREFIX / "include" / name)
flags = ["--prefix=" + PREFIX.as_posix(), "--target-os=mingw32", "--arch=x86_64",
         "--cc=x86_64-w64-mingw32-clang", "--cxx=x86_64-w64-mingw32-clang++",
         "--ar=llvm-ar", "--ranlib=llvm-ranlib", "--nm=llvm-nm", "--strip=llvm-strip",
         "--windres=x86_64-w64-mingw32-windres",
         "--disable-everything", "--disable-autodetect", "--disable-network",
         "--disable-programs", "--disable-doc", "--disable-debug", "--enable-small",
         "--enable-zlib", "--extra-cflags=-I" + (PREFIX / "include").as_posix(),
         "--extra-ldflags=-L" + (PREFIX / "lib").as_posix(),
         "--enable-shared", "--disable-static", "--enable-avcodec", "--enable-avformat",
         "--enable-avfilter", "--enable-avdevice", "--enable-swscale", "--enable-swresample",
         "--enable-demuxers", "--enable-parsers", "--enable-protocol=file",
         "--enable-decoder=" + ",".join(decoders), "--enable-encoder=flac,aac,pcm_s16le",
         "--enable-muxer=flac,wav,mp4,matroska,nut",
         "--enable-filter=abuffer,abuffersink,atrim,asetpts,aformat,aresample"]
old_flags = json.loads((ROOT / "configure-flags.json").read_text()) if (ROOT / "configure-flags.json").exists() else []
if not (BUILD / "config.h").exists() or flags != old_flags:
    run([BASH, SOURCE / "configure", *flags], BUILD, "configure.log")
(ROOT / "configure-flags.json").write_text(json.dumps(flags, indent=2))
run([MAKE, "-j4"], BUILD, "compile.log")
run([MAKE, "install"], BUILD, "install.log")
print("Built FFmpeg DLLs:", [(p.name, p.stat().st_size) for p in (PREFIX / "bin").glob("*.dll")], flush=True)

pyav = ROOT / "sources/av-16.0.1"
(pyav / "av/about.py").write_text('__version__ = "16.0.1+audio.1"\n', encoding="utf-8")
shutil.copy2(SOURCE / "COPYING.LGPLv2.1", pyav / "LICENSE.FFMPEG")
shutil.copy2(zlib / "LICENSE", pyav / "LICENSE.ZLIB")
(pyav / "LICENSE.FFMPEG-SOURCE").write_text(
    "Audio-focused FFmpeg 8.0.1 build; LGPL-2.1-or-later.\n"
    "Sources: https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz\n"
    "Zlib 1.3.1: https://zlib.net/fossils/zlib-1.3.1.tar.gz\n"
    "Build configuration:\n" + "\n".join(flags) + "\n", encoding="utf-8")
run([ROOT / "venv/Scripts/python.exe", "setup.py", "--ffmpeg-dir=" + str(PREFIX),
     "build_ext", "--compiler=mingw32", "-j4", "bdist_wheel"], pyav, "pyav-compile.log")
wheel = next((pyav / "dist").glob("av-16.0.1+audio.1-*.whl"))
run([ROOT / "venv/Scripts/python.exe", "-m", "delvewheel", "repair", "--add-path", PREFIX / "bin",
     "-w", ROOT / "wheels", wheel], ROOT, "repair.log")
print("Repaired wheel:", list((ROOT / "wheels").glob("*.whl")), flush=True)
