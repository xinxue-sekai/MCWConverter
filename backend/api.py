# -*- coding: utf-8 -*-
"""pywebview js_api 桥接层。

向 web UI 暴露以下方法：
  select_folder() / select_archive() / detect(path) / list_versions() /
  convert(path, version_number) / save_to() / pick_output() / cleanup()

转换在后台线程执行；进度通过
``window.evaluate_js("window.onProgress(JSON.stringify({...}))")`` 推送到前端，
payload 形如 ``{"type": "decrypt"|"convert", "done": n, "total": m}``，
完成/失败分别推送 ``{"type": "done", ...}`` / ``{"type": "error", ...}``。
"""

import json
import os
import re
import shutil
import tarfile
import tempfile
import threading
import zipfile

from . import WORK_ROOT
from . import convert as _convert
from . import detect as _detect


#: 支持的存档压缩包扩展名（不区分大小写）
ARCHIVE_EXTS = (".zip", ".mcworld", ".mctemplate", ".tar")

#: Windows 文件名非法字符
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_filename(name):
    """把任意字符串清洗为安全的文件夹名（替换非法字符、去首尾空格/点）。"""
    name = _INVALID_CHARS.sub("_", (name or "").strip())
    name = name.strip().strip(".")
    return name[:120]


def _perm_error_msg(path):
    """生成「拒绝访问」的用户友好提示（本机安全软件常拦截受保护目录写入）。"""
    return (
        f"拒绝访问：{path}。桌面、文档等目录可能被安全软件（如联想电脑管家）"
        "的文件夹保护拦截，未授权程序无法写入。请改选其他位置（例如 D 盘自建文件夹），"
        "或在安全软件中将本程序加入白名单后重试；也可以点击「保存到应用目录」。"
    )


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _extract_archive(archive_path, progress_cb=None):
    """把压缩包解压到临时目录，返回解压目录路径。"""
    ext = os.path.splitext(archive_path)[1].lower()
    tmp_dir = tempfile.mkdtemp(prefix="mcwc_arc_")

    if ext == ".tar":
        with tarfile.open(archive_path, "r:*") as tf:
            members = tf.getmembers()
            total = len(members)
            for i, member in enumerate(members):
                tf.extract(member, tmp_dir)
                if progress_cb is not None:
                    progress_cb("extract", i + 1, total)
    else:
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = zf.infolist()
            total = len(members)
            for i, member in enumerate(members):
                zf.extract(member, tmp_dir)
                if progress_cb is not None:
                    progress_cb("extract", i + 1, total)

    return tmp_dir


def _find_world_root(base_dir):
    """在解压目录中定位实际的世界根目录。

    部分压缩包内部直接是世界文件夹，部分会再套多层目录。
    递归查找包含 db/level.dat 的最深层子目录；否则返回 base_dir。
    """
    if os.path.isdir(os.path.join(base_dir, "db")):
        return base_dir

    candidates = []
    for root, dirs, files in os.walk(base_dir):
        if "db" in dirs and os.path.isdir(os.path.join(root, "db")):
            candidates.append(root)

    if candidates:
        # 返回层级最深（路径最长）的候选，通常就是实际世界根目录
        return max(candidates, key=lambda p: len(p.replace(base_dir, "").split(os.sep)))
    return base_dir


class ConverterApi:
    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._busy = False
        self._result_dir = None
        self._result_name = None
        self._result_version_str = None
        self._source_dir = None
        self._extract_dir = None
        self._work_tmp_dirs = []

    def set_window(self, window):
        self._window = window

    # ------------------------------------------------------------------
    def _emit(self, payload):
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                "window.onProgress(JSON.stringify("
                + json.dumps(_jsonable(payload), ensure_ascii=False)
                + "))"
            )
        except Exception:
            pass

    def _on_progress(self, stage, done, total):
        self._emit({"phase": stage, "done": done, "total": total})

    def _active_window(self):
        import webview

        if self._window is not None:
            return self._window
        if getattr(webview, "windows", None):
            return webview.windows[0]
        return None

    def _register_tmp(self, path):
        """登记需要在清理阶段删除的临时目录。"""
        if path and os.path.isdir(path) and path not in self._work_tmp_dirs:
            self._work_tmp_dirs.append(path)

    def _safe_rmtree(self, path):
        if path and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------------
    #  对话框
    # ------------------------------------------------------------------
    def select_folder(self):
        """选择网易存档文件夹，返回所选路径或 None。"""
        import webview

        win = self._active_window()
        if win is None:
            return None
        result = win.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            self._source_dir = result[0]
            return {"path": result[0], "world_name": None}
        return None

    def select_archive(self):
        """选择存档压缩包并解压，返回原路径与解压目录。"""
        import webview

        win = self._active_window()
        if win is None:
            return None

        # pywebview 的 file_types 要求为单个字符串或字符串元组，
        # 格式："描述 (*.ext1;*.ext2)"
        file_types = ("存档压缩包 (*.zip;*.mcworld;*.mctemplate;*.tar)",)
        result = win.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
        if not result or len(result) == 0:
            return None

        archive_path = result[0]
        ext = os.path.splitext(archive_path)[1].lower()
        if ext not in ARCHIVE_EXTS:
            raise ValueError(f"不支持的文件格式：{ext}，请选择 {', '.join(ARCHIVE_EXTS)} 之一")

        extract_dir = _extract_archive(archive_path, progress_cb=self._on_progress)
        self._extract_dir = extract_dir
        self._register_tmp(extract_dir)
        world_root = _find_world_root(extract_dir)
        return {"path": archive_path, "extracted_path": world_root}

    def pick_output(self):
        """选择结果输出目录，返回所选路径或 None。"""
        import webview

        win = self._active_window()
        if win is None:
            return None
        result = win.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    # ------------------------------------------------------------------
    #  探测与版本
    # ------------------------------------------------------------------
    def detect(self, path):
        """探测存档：世界名 / 平台 / 版本 / 各维度区块数。"""
        return _jsonable(_detect.detect(path, progress_cb=self._on_progress))

    def list_versions(self, platform="java"):
        """返回候选目标版本列表。"""
        return _jsonable(_convert.list_versions(platform))

    # ------------------------------------------------------------------
    #  转换（后台线程）
    # ------------------------------------------------------------------
    def convert(self, path, version_number=None):
        """启动一次后台转换任务。"""
        with self._lock:
            if self._busy:
                return {"ok": False, "error": "已有转换任务进行中"}
            self._busy = True
        self._result_dir = None

        def _work():
            out_dir = None
            try:
                out_dir = tempfile.mkdtemp(prefix="mcwc_out_")
                self._register_tmp(out_dir)
                result = _convert.convert_world(
                    path, out_path=out_dir,
                    version_number=version_number, progress_cb=self._on_progress,
                )
                self._result_dir = result["out_path"]
                self._result_name = result["world_name"]
                self._result_version_str = result.get("target_version_str")
                self._emit({"phase": "done", "ok": True, "result": _jsonable(result)})
            except Exception as exc:
                if out_dir is not None:
                    self._safe_rmtree(out_dir)
                    if out_dir in self._work_tmp_dirs:
                        self._work_tmp_dirs.remove(out_dir)
                self._emit({"phase": "error", "error": str(exc)})
            finally:
                self._busy = False

        threading.Thread(target=_work, daemon=True).start()
        return {"ok": True, "status": "started"}

    # ------------------------------------------------------------------
    #  保存
    # ------------------------------------------------------------------
    def default_save_name(self):
        """默认存档名：原存档名 + 转换后的版本号，如 ``我的世界_Java_1.20.4``。"""
        base = _safe_filename(self._result_name or "world")
        ver = _safe_filename(self._result_version_str or "")
        name = f"{base}_Java_{ver}" if ver else base
        return name or "world"

    def save_to(self, dest_dir=None, name=None):
        """把转换结果导出到指定目录（复制整份产物）。

        :param name: 输出目录名；为空时使用默认命名（原存档名_Java_版本号），
            重名时自动追加 _1/_2 序号避免冲突。
        :return: ``{"ok": True, "path": ...}`` 或 ``{"ok": False, "error": ...}``；
            用户取消目录选择时返回 None。
        """
        if self._result_dir is None or not os.path.isdir(self._result_dir):
            return {"ok": False, "error": "没有可保存的转换结果"}
        if dest_dir is None:
            dest_dir = self.pick_output()
        if not dest_dir:
            return None  # 用户取消选择
        return self._copy_result(dest_dir, name)

    def save_default(self, name=None):
        """保存到应用工作目录下的 saved/（不受桌面等受保护目录限制）。"""
        dest_dir = os.path.join(WORK_ROOT, "saved")
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"无法创建应用保存目录（{dest_dir}）：{exc}"}
        return self._copy_result(dest_dir, name)

    def _copy_result(self, dest_dir, name):
        """复制产物到 dest_dir/name（自动防重名），带写权限预检与友好报错。"""
        name = _safe_filename(name or self.default_save_name()) or "converted_world"
        final = self._unique_dir(dest_dir, name)

        # 写权限预检：安全软件拦截时在这里快速失败，避免复制一半才报错
        probe = os.path.join(dest_dir, f".mcwc_probe_{os.getpid()}")
        try:
            os.makedirs(probe)
            os.rmdir(probe)
        except PermissionError:
            return {"ok": False, "error": _perm_error_msg(dest_dir)}
        except OSError as exc:
            return {"ok": False, "error": f"目标目录不可写（{dest_dir}）：{exc}"}

        try:
            shutil.copytree(self._result_dir, final)
        except PermissionError:
            return {"ok": False, "error": _perm_error_msg(final)}
        except (OSError, shutil.Error) as exc:
            return {"ok": False, "error": f"保存失败：{exc}"}
        return {"ok": True, "path": final}

    @staticmethod
    def _unique_dir(parent, name):
        """在 parent 下生成不重复的目录名，若已存在则追加序号。"""
        candidate = os.path.join(parent, name)
        if not os.path.exists(candidate):
            return candidate
        i = 1
        while True:
            candidate = os.path.join(parent, f"{name}_{i}")
            if not os.path.exists(candidate):
                return candidate
            i += 1

    # ------------------------------------------------------------------
    #  清理
    # ------------------------------------------------------------------
    def cleanup(self):
        """清理所有由本实例创建的临时目录。"""
        # 复制列表避免遍历时修改
        for path in list(self._work_tmp_dirs):
            self._safe_rmtree(path)
        self._work_tmp_dirs.clear()
        if self._extract_dir:
            self._safe_rmtree(self._extract_dir)
            self._extract_dir = None
        self._result_dir = None
        self._result_name = None
        self._result_version_str = None
        return {"ok": True}
