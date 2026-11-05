# 精简媒体模块的来源与重建

这里是工具自带原生模块的构建资料，日常运行不需要构建工具链。

## 目录与加载

`program/vendor/cp313-win_amd64/` 包含 PyAV 模块、av.libs 下的 FFmpeg 动态库和许可文件。`program/jianying_asr/media_runtime.py` 根据 Python ABI 与平台选择它；其他环境使用该环境另行安装的 PyAV。普通 pip 依赖仍由 requirements.txt 管理。这一安排完全由工具内部实现，不要求天策后端增加依赖类型或特殊接口。

精简版保留 FFmpeg 内置的 210 种音频解码器、文件容器解析器、音频重采样、CPU SIMD 优化及 zlib。编码保留 FLAC，以及离线测试使用的 AAC、PCM；容器写入保留 FLAC、WAV、MP4、Matroska、NUT。移除视频编解码、外部编解码库、网络协议和设备采集。读取视频时只解码音轨，因此仍可从 MP4、MKV、WebM 等容器提取音频。

这不是通用视频处理库，请勿把它用于其他工具的视频处理。PyAV 包装层仍完整保留，不通过删除其中的 Python 模块或修改二进制导入表来猜测精简。

## 可复现输入

`sources.json` 列出实际使用的源码、工具链下载地址和 SHA-256；`audio-decoders.json` 固定解码器清单；`build.py` 保存完整编译配置及少量名称转换。`artifact.json` 记录验收时生成的 wheel 与库文件校验值。

- 构建主机：Windows x64，完整 CPython 3.13 和 Git for Windows（默认目录）。
- LLVM-MinGW 20261104 UCRT、MSYS make 4.4.1-2、NASM 2.16.03。
- FFmpeg 8.0.1、zlib 1.3.1、PyAV 16.0.1。
- 构建 Python 包：Cython 3.1.3、setuptools 80.9.0、wheel 0.45.1、delvewheel 1.11.2、pefile 2024.8.26。

## 重建步骤

在工具之外准备一个空构建目录，例如 `D:/asr-native-build`。按 sources.json 下载并校验归档；解压成以下结构。make 的 `.tar.zst` 需要支持 zstd 的归档工具。

```text
asr-native-build/
  compiler/llvm-mingw-20261104-ucrt-x86_64/bin/
  make/usr/bin/make.exe
  nasm/nasm-2.16.03/nasm.exe
  sources/ffmpeg-8.0.1/
  sources/av-16.0.1/
  sources/zlib-1.3.1/
```

在工具根目录执行（路径按实际修改）：

```powershell
python -m venv D:/asr-native-build/venv
D:/asr-native-build/venv/Scripts/python.exe -m pip install Cython==3.1.3 setuptools==80.9.0 wheel==0.45.1 delvewheel==1.11.2 pefile==2024.8.26
python native-build/build.py D:/asr-native-build
```

脚本编译 zlib 和 FFmpeg，再编译 PyAV，并用 delvewheel 将依赖 DLL 一起封装。PyAV 源码只修改 `av/about.py` 的本地版本标记；FFmpeg 与 zlib 源码不改。wheel 位于构建目录的 `wheels/`。先在独立目录解压验证，再将 wheel 全部内容放入工具的 `program/vendor/cp313-win_amd64/`；不要把编译器、源码树、对象文件和构建虚拟环境一起放进工具。

运行 `python -m unittest discover -s tests -v` 验证本地处理。分发重建版本时应保留各自许可、来源、对应构建配置及所需的对应源码分发材料。当前测试范围与边界见工具根目录 VALIDATION.md。
