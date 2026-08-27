# -*- mode: python ; coding: utf-8 -*-
"""MCWConverter PyInstaller 单文件打包配置。

构建（在已装好依赖的 Python 环境内）：
    pyinstaller --noconfirm --distpath release --workpath build/work build/MCWConverter.spec

说明：
  - PyInstaller 6.x 的 collect_submodules 会在隔离子进程里 import 包，而 amulet
    依赖未被注册的 rocksdb，导致收集失败。这里改用本地 os.walk 直接遍历包目录，
    收集全部 .py 子模块名与 .json.gz/.png 数据文件，规避该问题。
  - web / assets 以数据目录打入；rocksdb_stub 作为数据文件打入（backend/__init__.py
    运行期用 importlib 从文件路径动态加载）。
"""
import importlib.util
import os
import sys

# 项目根目录 = 本 spec 文件所在目录的上一级（build/ 的父目录）。
# 直接动态解析，避免在源码中硬编码本机绝对路径。
# PyInstaller 执行 spec 时 __file__ 未定义，故回退到 SPECPATH。
try:
    V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    V2 = os.path.dirname(SPECPATH)


def _install_rocksdb_stub():
    if "rocksdb" in sys.modules:
        return
    pkg_dir = os.path.join(V2, "backend", "rocksdb_stub")
    init_path = os.path.join(pkg_dir, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "rocksdb", init_path, submodule_search_locations=[pkg_dir]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rocksdb"] = module
    spec.loader.exec_module(module)


_install_rocksdb_stub()

import amulet  # noqa: E402
import PyMCTranslate  # noqa: E402


def _collect_pkg(pkg_name):
    """遍历包物理目录，返回 (子模块名列表, data 文件列表)。

    data 收集 .png / .json.gz / .json（Pygame 版本映射、图标资源）。
    """
    pkg = __import__(pkg_name)
    pkg_path = pkg.__path__[0]

    hidden = [pkg_name]
    datas = []

    for root, dirs, files in os.walk(pkg_path):
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, pkg_path)
            if f.endswith(".py"):
                parts = rel[:-3].split(os.sep)
                if parts and parts[-1] == "__init__":
                    parts = parts[:-1]
                if parts:
                    hidden.append(pkg_name + "." + ".".join(parts))
            elif f.endswith((".png", ".json.gz", ".json")):
                rel_dir = os.path.dirname(rel)
                dest = os.path.join(pkg_name, rel_dir) if rel_dir else pkg_name
                datas.append((full, dest))

    seen = set()
    hidden_out = []
    for m in hidden:
        if m not in seen:
            seen.add(m)
            hidden_out.append(m)
    return hidden_out, datas


amulet_hidden, amulet_datas = _collect_pkg("amulet")
pmct_hidden, pmct_datas = _collect_pkg("PyMCTranslate")

datas = amulet_datas + pmct_datas
datas += [(os.path.join(V2, "web"), "web")]
datas += [(os.path.join(V2, "assets"), "assets")]
datas += [(os.path.join(V2, "backend", "rocksdb_stub"), "backend/rocksdb_stub")]

hiddenimports = amulet_hidden + pmct_hidden

a = Analysis(
    [os.path.join(V2, "run.py")],
    pathex=[V2],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MCWConverter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 最终交付：GUI 应用，无控制台窗口
    disable_windowed_traceback=False,
    icon=None,
)
