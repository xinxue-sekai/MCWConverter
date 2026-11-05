# -*- coding: utf-8 -*-
"""出错留痕：把原本被 ``except Exception: pass`` 吞掉的异常写进 work/logs/app.log。

只做一件事，只用标准库：
  - 日志目录跟着 WORK_ROOT 走（开发模式 <仓库>/work/logs，打包后在 exe 同级 work/logs）
  - 单个文件 1MB、留 3 份历史，不会无限长
  - 任何一步装配失败都只是「少一条日志」，绝不影响转换与保存主流程
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from . import WORK_ROOT

LOGGER_NAME = "mcwconverter"
LOG_FILE_NAME = "app.log"
_MAX_BYTES = 1024 * 1024
_BACKUPS = 3
_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(message)s"

_ready = False


def log_dir():
    return os.path.join(WORK_ROOT, "logs")


def log_path():
    return os.path.join(log_dir(), LOG_FILE_NAME)


def get_logger():
    """返回项目共用的 logger；首次调用时装配文件 handler，装不上就退化为不写。"""
    global _ready
    logger = logging.getLogger(LOGGER_NAME)
    if _ready:
        return logger
    _ready = True
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        os.makedirs(log_dir(), exist_ok=True)
        handler = RotatingFileHandler(
            log_path(), maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger


def log_swallowed(what, payload=None):
    """记录一处「本来会被静默吞掉」的异常；自身绝不抛错。

    必须在 ``except`` 块内调用，回溯信息取自当前正在处理的异常。
    """
    try:
        suffix = ""
        if isinstance(payload, dict) and payload.get("phase"):
            suffix = f"（阶段：{payload['phase']}）"
        get_logger().exception("%s%s", what, suffix)
    except Exception:
        pass
