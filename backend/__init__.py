# -*- coding: utf-8 -*-
"""MCWConverter 后端包。

导入本包会自动完成两项运行时基础设施（顺序敏感）：
  1. 把纯 Python ``rocksdb`` 占位包注册到 ``sys.modules``（替代 amulet-rocksdb
     这一无法在无 MSVC 环境编译的 C++ 扩展）；
  2. 调用 ``env_fix.apply()`` 把 TEMP/TMP 与 amulet 缓存目录重定向到本地安全路径
     （规避 amulet 内部 ``tempfile.mkdtemp`` 死循环卡死）。

这两步必须发生在任何 ``import amulet`` 之前。
"""

import importlib.util
import os
import sys


def _install_rocksdb_stub():
    """把 backend/rocksdb_stub 注册为顶层 `rocksdb` 模块。"""
    if "rocksdb" in sys.modules:
        return
    pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rocksdb_stub")
    init_path = os.path.join(pkg_dir, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "rocksdb", init_path, submodule_search_locations=[pkg_dir]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rocksdb"] = module
    spec.loader.exec_module(module)


_install_rocksdb_stub()

from . import env_fix as _env_fix  # noqa: E402

WORK_ROOT = _env_fix.apply()

__all__ = ["WORK_ROOT"]