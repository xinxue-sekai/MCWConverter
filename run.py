# -*- coding: utf-8 -*-
"""MCWConverter 桌面应用入口（pywebview 加载 web/index.html）。"""

import atexit
import os
import shutil
import sys
import tempfile

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# 必须在 import backend 之前记录：backend.env_fix 会把 TEMP 重定向到 work 目录，
# 而 PyInstaller 的 _MEI 目录始终位于系统真实临时目录下。
_SYSTEM_TEMP = tempfile.gettempdir()

from backend import api as _api  # noqa: E402  触发 rocksdb stub + env_fix
from backend import WORK_ROOT  # noqa: E402


def _rmtree_force(path):
    """删除目录；对只读文件（_MEI 解压产物可能带只读属性）改权限后重试。"""

    def _on_exc(func, p, _exc):
        try:
            os.chmod(p, 0o666)
            func(p)
        except Exception:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_on_exc)
        else:
            shutil.rmtree(path, onerror=lambda f, p, e: _on_exc(f, p, e))
    except Exception:
        pass


def _cleanup_leftover_mei():
    """启动时清理上次运行残留的 PyInstaller _MEI 临时目录。"""
    if sys.platform != "win32":
        return
    tmp = _SYSTEM_TEMP
    if not tmp or not os.path.isdir(tmp):
        return
    current_mei = getattr(sys, "_MEIPASS", None)
    for name in os.listdir(tmp):
        if not name.startswith("_MEI"):
            continue
        path = os.path.join(tmp, name)
        if current_mei and os.path.abspath(path) == os.path.abspath(current_mei):
            continue
        _rmtree_force(path)


def _cleanup(api_obj):
    """应用退出前的统一清理：结果临时目录、archive 解压目录、本地 work 缓存。"""
    try:
        api_obj.cleanup()
    except Exception:
        pass

    for sub in ("tmp", "cache"):
        path = os.path.join(WORK_ROOT, sub)
        if os.path.isdir(path):
            try:
                for name in os.listdir(path):
                    full = os.path.join(path, name)
                    if os.path.isdir(full):
                        shutil.rmtree(full, ignore_errors=True)
            except Exception:
                pass


def main():
    import webview

    _cleanup_leftover_mei()

    api_obj = _api.ConverterApi()
    index_html = os.path.join(_BASE, "web", "index.html")
    window = webview.create_window(
        "我的世界存档转换器",
        index_html,
        js_api=api_obj,
        width=780,
        height=620,
        min_size=(640, 520),
    )
    api_obj.set_window(window)

    def _on_closing():
        api_obj.cleanup()

    window.events.closing += _on_closing

    atexit.register(_cleanup, api_obj)

    try:
        webview.start()
    finally:
        _cleanup(api_obj)


if __name__ == "__main__":
    main()
