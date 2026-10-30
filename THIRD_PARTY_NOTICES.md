# 第三方组件与许可说明

本文件对应 Note Flash 0.3.0 的 Windows Qt 候选版本。项目自身代码采用根目录 `LICENSE` 中的 MIT 许可；该许可不替代下列组件、图标、运行库及其内含代码的许可。组件名称和商标归各自权利人所有。

源码项目包仅包含本项目代码、素材、文档和许可文本，不包含 `.runtime-deps`、`.build-deps` 或第三方运行库二进制。安装器和便携包会包含运行库，因此还需要遵守对应二进制再分发条款。**本文件记录已收集的文本和已知范围，不表示所有二进制分发条件已审查完毕；尚未完成项见文末。**

## 组件、版本与文本

| 组件 | 本次使用版本与用途 | 许可及本地文本 |
| --- | --- | --- |
| Qt / PySide6-Essentials / Shiboken6 | 6.10.2，桌面控件与 Python 绑定；Qt Core、GUI、Widgets、Network、SVG 及随包插件 | 选择开源 LGPLv3 路径；[LGPLv3](licenses/LGPL-3.0-only.txt) 和其并入的 [GPLv3](licenses/GPL-3.0-only.txt)。发行件元数据也列出 GPLv2/GPLv3 选项，[GPLv2](licenses/GPL-2.0-only.txt)一并保留。版权及第三方例外见下节。 |
| Python | 3.13.5，安装包内解释器 | [PSF 与历史许可全文](licenses/Python-3.13.5-LICENSE.txt)；Python 内含组件仍适用各自许可。 |
| Tcl / Tk | 8.6.15，中文安装与卸载界面 | [Tcl](licenses/Tcl-8.6.15-license.terms)、[Tk](licenses/Tk-8.6.15-license.terms)。 |
| OpenSSL | 3.0.16，Python 所带 `libcrypto-3.dll` | [Apache 2.0](licenses/OpenSSL-3.0.16-LICENSE.txt)。 |
| zlib | 1.3.1，Python 所带 `zlib1.dll`；Qt 内嵌版本另见归属清单 | [zlib 许可](licenses/zlib-1.3.1-LICENSE.txt)。 |
| libffi | 3.4.4，CPython 3.13.5 Windows 构建声明的外部依赖 | [MIT 许可](licenses/libffi-LICENSE.txt)。该 DLL 本身未提供版本资源，版本依据官方构建配置。 |
| bzip2 / liblzma | bzip2 1.0.8、XZ 5.2.5，Python `_bz2` / `_lzma` 扩展 | [bzip2](licenses/bzip2-1.0.8-LICENSE.txt)、[XZ 分组件许可说明](licenses/xz-5.2.5-COPYING.txt)。实际使用 liblzma；未把 XZ 命令行工具加入本项目。 |
| mpdecimal | 4.0.0，Python `_decimal`；已查询当前解释器 `decimal.__libmpdec_version__` | [BSD 版权与许可](licenses/mpdecimal-4.0.0-COPYRIGHT.txt)。 |
| PyInstaller | 6.22.3，构建工具及生成程序的 bootloader | [GPLv2-or-later 与 Bootloader Exception 原文](licenses/PyInstaller-6.22.3-COPYING.txt)。例外允许生成应用采用自己的许可，但不免除应用依赖的义务。 |
| GitHub Octicons `mark-github-16` | GitHub 仓库入口图标；Copyright © 2026 GitHub Inc. | [MIT 许可](assets/branding/octicons-LICENSE.txt)，亦备份于 [licenses](licenses/Octicons-MIT.txt)。GitHub 标识不表示 GitHub 为本软件背书。 |

Python 外部组件版本依据 [CPython 3.13.5 官方构建配置](https://github.com/python/cpython/blob/v3.13.5/PCbuild/python.props)，副本见 [许可证目录中的版本依据](licenses/CPython-3.13.5-external-versions.props)。OpenSSL、Tcl/Tk、zlib 的版本也已核对本地候选 DLL 文件版本。所有下载文本的官方来源和 SHA256 记录在 [sources.json](licenses/sources.json)。

## Qt 自带第三方代码

Qt 的 LGPL/GPL 文本不覆盖其中所有第三方代码。已按 **Qt 6.10.2** 官方源标签收集 `qtbase`、`qtsvg`、`qtimageformats` 三个模块的 `src/` 归属记录及所引用的许可证、版权文本：

- [85 条上游归属、版本、版权、许可标识和源码位置](licenses/qt-6.10.2-attributions.json)。
- [Qt Base 许可证与归属文本](licenses/qt-6.10.2/qtbase/)，含文本渲染、压缩、Unicode、正则、图像等组件。
- [Qt SVG 许可证与归属文本](licenses/qt-6.10.2/qtsvg/)。
- [Qt Image Formats 许可证与归属文本](licenses/qt-6.10.2/qtimageformats/)，包括 libtiff 4.7.1、libwebp 1.6.0。

该归属集合是上述源模块的**保守超集**，包含部分其他平台或构建选项专用组件，并不是说本 Windows 程序实际链接了全部 85 项。上游的 `QtUsage`、`LicenseId`、`Copyright` / `CopyrightFile` 等字段原样保留；`LicenseFile` 与 `LicenseFiles` 所引用文本均已收集。根目录和各模块的通用许可文本也一并保留。未把 Qt 示例代码、额外应用或第三方运行依赖下载进源码包。

Qt 官方说明与模块归属索引：[Qt 开源许可义务](https://www.qt.io/development/open-source-lgpl-obligations)、[Qt 6.10 第三方说明](https://doc.qt.io/qt-6.10/licenses-used-in-qt.html)、[Qt for Python 6.10 第三方说明](https://doc.qt.io/qtforpython-6.10/licenses.html)。在线 6.10 文档可能随补丁版本更新，本目录的归属记录固定来自 `v6.10.2`，不能混用较新补丁版本的组件版本号。

## 对应源码与替换 Qt

本项目没有修改 Qt、PySide6、Shiboken、Python 等上游库的源代码。对应源码可从以下官方位置获取；这些是源码获取地址，不是本项目重新许可的文件：

| 组件 | 对应源码 |
| --- | --- |
| Qt 6.10.2 | [官方 6.10.2 源码目录](https://download.qt.io/archive/qt/6.10/6.10.2/single/)；[qtbase](https://github.com/qt/qtbase/tree/v6.10.2)、[qtsvg](https://github.com/qt/qtsvg/tree/v6.10.2)、[qtimageformats](https://github.com/qt/qtimageformats/tree/v6.10.2)。 |
| PySide6 / Shiboken6 6.10.2 | [官方源仓库标签](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.10.2)、[官方镜像](https://github.com/qtproject/pyside-pyside-setup/tree/v6.10.2)、[从源码构建说明](https://doc.qt.io/qtforpython-6.10/building_from_source/index.html)。 |
| Python 3.13.5 与 Windows 外部依赖 | [CPython v3.13.5](https://github.com/python/cpython/tree/v3.13.5)、[官方外部依赖源仓库](https://github.com/python/cpython-source-deps)。 |
| Tcl / Tk 8.6.15 | [Tcl](https://github.com/tcltk/tcl/tree/core-8-6-15)、[Tk](https://github.com/tcltk/tk/tree/core-8-6-15)。 |
| OpenSSL 3.0.16 / zlib 1.3.1 / libffi 3.4.4 | [OpenSSL](https://github.com/openssl/openssl/tree/openssl-3.0.16)、[zlib](https://github.com/madler/zlib/tree/v1.3.1)、[libffi](https://github.com/libffi/libffi/tree/v3.4.4)。 |
| PyInstaller 6.22.3 | [官方源码](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3)、[官方 bootloader 例外说明](https://pyinstaller.org/en/stable/license.html)。 |

本项目使用动态 Qt DLL，不禁止为调试修改版 LGPL 库而进行逆向工程或替换。可按官方构建说明生成与 Python 3.13 / Windows x64 兼容的 Qt、PySide6、Shiboken，放入开发环境的 `.runtime-deps` 后运行项目源码，或使用项目构建脚本重建候选程序。二进制的 Qt/PySide DLL 位于程序目录的 `_internal` 中；替换时应保持 Qt、PySide 与 Shiboken 之间的 ABI 一致。源码、构建脚本及运行入口均可获得，不设置阻止修改版库运行的签名校验。

**二进制发布者仍须实际落实 LGPL 的对应源码可获得性、许可告知及重新组合/安装信息义务。上游下载链接不是本项目已代发布者履行书面源码提供承诺的声明。** 本地准备阶段不作尚未落实的书面提供承诺，也不把单独添加 MIT 文件当作全部依赖已经合规。

## Windows 运行库、软件 OpenGL 与尚未覆盖项

1. 候选中含 Microsoft `MSVCP140*.dll`（14.44.35211.0）和 `VCRUNTIME140*.dll`（14.42.34438.0），由本机用于构建的 Python/Qt 发行件带入。它们是 Microsoft 专有运行库，**不受本项目 MIT 或 Qt LGPL 授权**，再分发适用 Microsoft 独立条款。见 [Microsoft 再分发说明](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)、[Visual Studio 2022 可分发清单](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)及 [官方运行库下载入口](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。本目录未改写或重新许可 Microsoft EULA。
2. Qt wheel 附带 `PySide6/opengl32sw.dll`，候选二进制字符串可识别 **Mesa 11.2.2 / LLVM 3.6.2**。已保留 [Mesa 11.2.2 官方版权与许可](licenses/Mesa-11.2.2-license.html)、[LLVM 3.6.2 许可](licenses/LLVM-3.6.2-LICENSE.txt)及其 [OpenBSD regex](licenses/LLVM-3.6.2-OpenBSD-regex.txt)、[ARM](licenses/LLVM-3.6.2-ARM-LICENSE.txt)、[MD5](licenses/LLVM-3.6.2-MD5-notice.txt)附加声明。[Mesa 对应版本官方源码](https://archive.mesa3d.org/older-versions/11.x/11.2.2/)与 [LLVM 对应源码](https://github.com/llvm/llvm-project/tree/llvmorg-3.6.2)可分别获取；Mesa 许可从该源码档案在内存中提取，档案未保留、运行二进制未下载。[Qt 官方预构建目录](https://download.qt.io/development_releases/prebuilt/llvmpipe/windows/)亦列出这个软件渲染器。**尚未取得该历史预构建二进制的完整构建记录及逐对象归属映射，公开分发前仍需确认实际构建包含的子组件。** 没有用当前 Mesa 版本的文本冒充该历史版本许可。
3. Qt 的 85 条归属记录是源模块的保守超集，不等同于最终二进制 SBOM；尚待核对项主要是上条软件 OpenGL 预构建件的具体子组件映射。
4. Windows 自带 ICU 由操作系统提供；修正后的候选不包含外来 `icu*.dll`。不将此前误入构建的 Poppler ICU 视为本项目的分发组件。

以上缺口针对**包含 vendor 二进制的安装器/便携包**。源码项目包不携带这些 vendor DLL，不能据此把源代码的 MIT 许可误写成 GPL，也不能反过来用 MIT 覆盖 vendor 的权利。

## 图片与行为参考

- `assets/branding/note-flash.png`、其 ICO，以及当前宠物原图为本项目会话中生成并经用户确认的图像；补充动作图的来源和生成记录见 `assets/pets/generation.json`。它们不是从 VPet 或 Shimeji 仓库复制的角色素材。
- VPet 和 Shimeji 仅用于理解动作阶段、帧时序与停顿策略，项目记录说明没有复制其引擎代码或角色图；不因此把它们列为已打包依赖。
- `github-mark.svg` 是 Octicons 的第三方图标，必须继续保留其 MIT 版权和许可，不应删除 `octicons-LICENSE.txt`。
