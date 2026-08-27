# -*- coding: utf-8 -*-
"""运行时环境修复：把临时目录与 amulet 缓存目录重定向到本地安全路径。

已验证的坑（见 conversion/ 目录的开发经验）：
  1. amulet 的 TempDir 使用 ``AMULET_LEVEL_CACHE_DIR``（或其父 ``CACHE_DIR``）
     作为 mkdtemp 目标目录；默认缓存目录（platformdirs.user_cache_dir）在部分
     Windows 环境会导致 ``tempfile.mkdtemp`` 内部重试死循环卡死。
  2. amulet 的 ``api/cache.py`` 在模块导入时就会调用 ``tempfile.gettempdir()``
     （受 ``TEMP``/``TMP`` 环境变量影响），因此必须在 ``import amulet`` 之前
     完成重定向，否则导入阶段即可能卡死。

本模块必须在任何 ``import amulet`` 之前执行（由 ``backend/__init__.py`` 保证）。
"""

import os
import sys
import tempfile
import time


def _try_make(path):
    """容错创建目录：部分安全软件会对新目录做扫描，首次创建可能瞬时拒绝访问。"""
    for _ in range(3):
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except OSError:
            if os.path.isdir(path):
                return True
            time.sleep(0.2)
    return os.path.isdir(path)


def _default_work_root():
    """选择运行时工作根目录。

    开发模式：<v2>/work。
    打包模式：绝不能使用 _MEI 临时目录（__file__ 所在目录），否则 TEMP/WebView2
    用户数据都会落在 _MEI 里，webview 子进程持有 _MEI 文件锁，导致 PyInstaller
    bootloader 退出时删除临时目录失败弹警告。依次尝试：exe 同级 work 目录、
    系统 TEMP 下的 MCWConverter 目录、唯一临时目录。
    """
    if not getattr(sys, "frozen", False):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "work",
        )
    candidates = []
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates.append(os.path.join(exe_dir, "work"))
    sys_tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if sys_tmp:
        candidates.append(os.path.join(sys_tmp, "MCWConverter"))
    for cand in candidates:
        if _try_make(cand):
            return cand
    return tempfile.mkdtemp(prefix="MCWConverter_work_")


def apply(work_root=None):
    """重定向 TEMP/TMP 与 amulet 缓存目录到本地安全路径。

    :param work_root: 运行时工作根目录；None 时自动选择（见 _default_work_root）。
    :return: 工作根目录绝对路径
    """
    if work_root is None:
        work_root = _default_work_root()
    work_root = os.path.abspath(work_root)
    _try_make(work_root)

    tmp_dir = os.path.join(work_root, "tmp")
    cache_dir = os.path.join(work_root, "cache")
    level_cache_dir = os.path.join(cache_dir, "level_data")
    for d in (tmp_dir, cache_dir, level_cache_dir):
        os.makedirs(d, exist_ok=True)

    # 1) 重定向临时目录（tempfile.gettempdir / mkdtemp 受影响）
    os.environ["TEMP"] = tmp_dir
    os.environ["TMP"] = tmp_dir

    # 2) 接管 amulet 缓存目录（规避 mkdtemp 卡死的最关键一步）
    os.environ["AMULET_LEVEL_CACHE_DIR"] = level_cache_dir
    os.environ["CACHE_DIR"] = cache_dir  # 强制覆盖，amulet 内部 setdefault 不会再生效

    # 3) 重置 tempfile 模块缓存的路径，强制其重新解析环境变量
    try:
        tempfile.tempdir = None
    except Exception:
        pass

    return work_root
