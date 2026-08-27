# -*- coding: utf-8 -*-
"""源存档探测：世界名 / 平台 / 版本 / 各维度区块数。

世界名优先读 ``levelname.txt``（网易基岩存档自带的明文世界名文件），
其次回退到 level.dat；平台/版本/维度区块数通过 amulet 读取（需解密后的
LevelDB 目录）。解密与探测始终在副本上进行，不改原档。
"""

import os
import shutil

from .decrypt import decrypt


def _compound_of(tag):
    if tag is None:
        return None
    comp = getattr(tag, "compound", None)
    if comp is not None:
        return comp
    return tag


def load_level_dat(path):
    """稳健解析 level.dat（自动处理 Java gzip / 基岩小端头）。

    :return: 根 CompoundTag；解析失败返回 None
    """
    from amulet_nbt import load as nbt_load

    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw:
        return None

    if raw[:2] == b"\x1f\x8b":  # gzip
        return _compound_of(nbt_load(path, compressed=True))
    if raw[:2] in (b"\x78\x01", b"\x78\x9c", b"\x78\x9a", b"\x78\xda"):  # zlib
        return _compound_of(nbt_load(path, compressed=True))

    # 基岩 level.dat：4 字节小端版本号 + 4 字节长度，之后未压缩小端 NBT
    if len(raw) >= 8:
        lead = int.from_bytes(raw[:4], "little", signed=True)
        if 3 <= lead <= 10:
            try:
                return _compound_of(
                    nbt_load(raw[8:], compressed=False, little_endian=True)
                )
            except Exception:
                pass

    # 兜底：标准未压缩（大端/小端各试一次）
    for little in (False, True):
        try:
            return _compound_of(nbt_load(raw, compressed=False, little_endian=little))
        except Exception:
            continue
    return None


def read_world_meta(world_dir):
    """读取世界展示名（不改档、不依赖解密）。"""
    world_dir = os.path.abspath(world_dir)
    name = None

    levelname_txt = os.path.join(world_dir, "levelname.txt")
    if os.path.isfile(levelname_txt):
        try:
            with open(levelname_txt, "r", encoding="utf-8-sig") as fh:
                text = fh.read().strip()
            if text:
                name = text
        except Exception:
            pass

    if not name:
        root = load_level_dat(os.path.join(world_dir, "level.dat"))
        if root is not None:
            try:
                lv = root.get_string("LevelName")
                if lv is not None and lv.py_str:
                    name = lv.py_str
            except Exception:
                pass

    if not name:
        name = os.path.basename(world_dir)
    return {"name": name}


def version_str(version):
    """把版本号（元组 / 整数 / 字符串）格式化为可读字符串。"""
    if isinstance(version, (tuple, list)):
        return ".".join(str(x) for x in version)
    return str(version)


#: amulet 维度名 -> 界面友好名（用于展示，不影响转换逻辑）
_DIM_FRIENDLY = {
    "minecraft:overworld": "主世界",
    "minecraft:the_nether": "下界",
    "minecraft:the_end": "末地",
    "overworld": "主世界",
    "the_nether": "下界",
    "the_end": "末地",
    "nether": "下界",
    "end": "末地",
}


def chunk_counts(world_dir):
    """用 amulet 读取平台 / 版本 / 各维度区块数。

    :param world_dir: 已解密的 LevelDB 世界目录
    """
    import amulet

    world = amulet.load_level(world_dir)
    try:
        platform = world.level_wrapper.platform
        version = world.level_wrapper.version
        counts = {}
        for d in world.dimensions:
            key = _DIM_FRIENDLY.get(d, d)
            counts[key] = len(list(world.level_wrapper.all_chunk_coords(d)))
    finally:
        world.close()

    return {
        "platform": platform,
        "version": version_str(version),
        "dimensions": counts,
        "total_chunks": sum(counts.values()),
    }


def detect(path, decrypted=False, progress_cb=None):
    """探测一个网易存档目录。

    :param path: 源存档目录（可能加密）
    :param decrypted: path 已是解密目录（跳过解密复制，直接 amulet 读取）
    :param progress_cb: ``fn(done: int, total: int)`` 解密阶段文件进度回调
    :return: {"name", "platform", "version_str", "dimensions", "total_chunks"}
    """
    info = read_world_meta(path)

    if decrypted:
        world_dir = os.path.abspath(path)
        info.update(chunk_counts(world_dir))
    else:
        world_dir = decrypt(path, progress_cb=progress_cb)
        try:
            info.update(chunk_counts(world_dir))
        finally:
            shutil.rmtree(world_dir, ignore_errors=True)

    return {
        "world_name": info.get("name"),
        "platform": info.get("platform"),
        "version": info.get("version"),
        "dimensions": info.get("dimensions", {}),
        "total_chunks": info.get("total_chunks", 0),
    }