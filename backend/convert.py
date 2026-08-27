# -*- coding: utf-8 -*-
"""基岩 -> Java 转换引擎（基于 amulet-core）。

核心链路（与 conversion/convert.py 一致、已验证）：
  amulet.load_level(解密后目录) -> AnvilFormat(out_path).create_and_open("java", version)
  -> world.save(wrapper=anvil, progress_callback=...) -> anvil.close(); world.close()
  -> 重建完整 level.dat（见 leveldat.py）

目标版本约束：
  - 默认 Java 1.20.4（DataVersion 3700，旧式维度目录布局）；禁止使用未来版本
    （如 26.x）——其新式维度目录会导致维度表为空、不写区块。
  - 候选版本用 ``world.translation_manager.version_numbers("java")`` 推导，
    偏好列表 1.20.4 / 1.21.4 / 1.21.1 / 1.20.1 / 1.19.4；低于默认首选属"降级"，
    通过在结果中标记 ``downgrade=True`` 提示有损。
"""

import os
import shutil
import tempfile

from .decrypt import decrypt

#: Java 目标版本偏好（优先级从高到低，均为实测安全的旧式布局版本）
JAVA_PREFERRED = [(1, 20, 4), (1, 21, 4), (1, 21, 1), (1, 20, 1), (1, 19, 4)]


def parse_version(value):
    """把版本号（None / "1.20.4" / (1,20,4) / [1,20,4]）规范化为元组。"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        try:
            return tuple(int(x) for x in value.split(".") if x != "")
        except Exception:
            raise ValueError(f"非法版本号: {value!r}")
    if isinstance(value, (tuple, list)):
        try:
            return tuple(int(x) for x in value)
        except Exception:
            raise ValueError(f"非法版本号: {value!r}")
    raise ValueError(f"非法版本号: {value!r}")


def list_versions(platform="java"):
    """返回指定平台全部可用版本的结构化列表（供 UI 展示）。

    Java 侧过滤掉采用「新式维度目录」布局的版本（DataVersion >= 4786，如 26.x），
    这些版本转换引擎无法写入区块（详见 convert() 的防御断言）。
    """
    import PyMCTranslate

    tm = PyMCTranslate.new_translation_manager()
    preferred0 = JAVA_PREFERRED[0] if platform == "java" else None
    result = []
    for v in sorted(tm.version_numbers(platform), reverse=True):
        data_version = tm.get_version(platform, v).data_version
        if platform == "java" and data_version >= 4786:
            continue  # 新式维度目录布局，转换引擎不支持
        result.append({
            "label": ".".join(str(x) for x in v),
            "data_version": data_version,
            "recommended": platform == "java" and v == preferred0,
            "lossy": platform == "java" and preferred0 is not None and v < preferred0,
            "beta": False,
            "platform": platform,
        })
    return result


def choose_version(tm, platform="java", version_number=None):
    """按偏好回退列表选择目标版本。

    :param tm: PyMCTranslate.TranslationManager（世界自带的 translation_manager）
    :param version_number: 用户指定目标版本元组（None 时用偏好策略）
    :raises ValueError: 指定版本不受支持
    """
    available = set(tm.version_numbers(platform))
    if not available:
        raise ValueError(f"没有可用于 {platform} 的转换目标版本")

    requested = parse_version(version_number)
    if requested is not None:
        if requested in available:
            return requested
        hint = ", ".join(
            ".".join(str(x) for x in v) for v in JAVA_PREFERRED if v in available
        )
        raise ValueError(
            f"目标版本 {'.'.join(str(x) for x in requested)} 不受支持；"
            f"建议使用: {hint or '任一可用版本'}"
        )

    for v in JAVA_PREFERRED:
        if v in available:
            return v
    return max(available)


def convert(decrypted_dir, out_path, version_number=None, progress_cb=None):
    """把已解密世界转换为 Java Anvil 并重建 level.dat。

    :param decrypted_dir: 解密后的基岩 LevelDB 世界目录
    :param out_path: 输出 Java Anvil 目录（已存在会被覆盖重建）
    :param version_number: 目标版本（元组 / 字符串 / None=自动）；仅支持 "java"
    :param progress_cb: ``fn(stage: str, done: int, total: int)``，
                        stage 为 "convert"
    :return: 转换统计 dict（含 world_name / seed / data_version / dimensions 等）
    """
    import amulet
    from amulet.level.formats.anvil_world.format import AnvilFormat

    decrypted_dir = os.path.abspath(decrypted_dir)
    out_path = os.path.abspath(out_path)

    world = amulet.load_level(decrypted_dir)
    try:
        source_platform = world.level_wrapper.platform
        source_version = world.level_wrapper.version
        tm = world.translation_manager

        target = choose_version(tm, "java", version_number)
        data_version = tm.get_version("java", target).data_version
        counts = {
            d: len(list(world.level_wrapper.all_chunk_coords(d)))
            for d in world.dimensions
        }

        anvil = AnvilFormat(out_path)
        anvil.create_and_open("java", target, overwrite=True)
        try:
            # 防御断言：未来版本（如 26.x）使用新式维度目录布局，创建后维度表
            # 为空，world.save 会静默跳过导致不写区块
            if not list(anvil.dimensions):
                raise ValueError(
                    f"目标版本 {'.'.join(str(x) for x in target)} 使用新式维度布局，"
                    "转换引擎无法写入区块；请改用偏好列表中的稳定版本（如 Java 1.20.4）"
                )

            def _relay(done, total_):
                if progress_cb is not None:
                    progress_cb("convert", done, total_)

            world.save(wrapper=anvil, progress_callback=_relay)
        finally:
            anvil.close()
    finally:
        world.close()

    # ---- 转换完成后重建完整 level.dat ----
    from . import leveldat as _leveldat
    from .detect import read_world_meta, version_str

    name = read_world_meta(decrypted_dir)["name"]
    seed = _leveldat.read_seed(decrypted_dir)
    _leveldat.build_level_dat(out_path, name, seed, data_version, target)

    return {
        "world_name": name,
        "seed": seed,
        "source_platform": source_platform,
        "source_version": version_str(source_version),
        "target_platform": "java",
        "target_version": list(target),
        "target_version_str": ".".join(str(x) for x in target),
        "data_version": data_version,
        "dimensions": dict(counts),
        "total_chunks": sum(counts.values()),
        "out_path": out_path,
        "downgrade": target < JAVA_PREFERRED[0],
    }


def convert_world(src_folder, out_path=None, version_number=None, progress_cb=None):
    """端到端转换：解密（副本） -> 转换 -> 重建 level.dat。

    供 GUI 后端调用；``src_folder`` 为原始网易加密存档目录，原档全程只读。

    :return: convert() 的统计 dict
    """
    if out_path is None:
        out_path = tempfile.mkdtemp(prefix="mcwc_out_")
    else:
        out_path = os.path.abspath(out_path)

    decrypted_dir = None
    try:
        def _decrypt_relay(done, total_):
            if progress_cb is not None:
                progress_cb("decrypt", done, total_)

        decrypted_dir = decrypt(src_folder, progress_cb=_decrypt_relay)
        return convert(
            decrypted_dir, out_path=out_path,
            version_number=version_number, progress_cb=progress_cb,
        )
    finally:
        if decrypted_dir is not None:
            shutil.rmtree(decrypted_dir, ignore_errors=True)