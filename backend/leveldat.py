# -*- coding: utf-8 -*-
"""重建完整合法的 Java level.dat。

动机（已验证的坑）：amulet 转换引擎写出的 level.dat 极简（仅 version /
DataVersion / LastPlayed / LevelName），缺少 WorldGenSettings、出生点、
游戏类型、玩家、世界边界等 Java 必需字段，Java 客户端会判定
"存档包含无效或损坏的数据"。因此转换完成后必须重建为标准完整结构。

字段集复刻 conversion/build_leveldat.py，并补上 Player / DataPacks
（均为 Java 单机打开所必需的最小合法结构）。
"""

import os
import time

#: Java level.dat 遗留的"世界格式版本"字段（自 1.16 起冻结为 19133）
LEGACY_WORLD_VERSION = 19133


def _tag_int(tag):
    if tag is None:
        return None
    for attr in ("py_int", "py_float"):
        if hasattr(tag, attr):
            try:
                return int(getattr(tag, attr))
            except Exception:
                pass
    try:
        return int(tag)
    except Exception:
        return None


def read_seed(world_dir):
    """从源世界 level.dat 读取种子（保持未探索区域地形连续性）。

    Java 优先 ``Data.WorldGenSettings.seed`` / ``Data.RandomSeed``；
    基岩在根层读 ``RandomSeed`` / ``worldSeed`` / ``world_seed``；
    读取失败一律兜底 0。
    """
    from amulet_nbt import CompoundTag

    from .detect import load_level_dat

    root = load_level_dat(os.path.join(world_dir, "level.dat"))
    if root is None:
        return 0

    seed = None

    data = None
    try:
        data = root.get_compound("Data")
    except Exception:
        data = None
    if data is not None and len(data) > 0:
        try:
            wgs = data.get_compound("WorldGenSettings")
            if wgs is not None and "seed" in wgs:
                seed = _tag_int(wgs.get("seed"))
        except Exception:
            pass
        if seed is None:
            seed = _tag_int(data.get("RandomSeed"))

    if seed is None:
        for key in ("RandomSeed", "worldSeed", "world_seed"):
            if key in root:
                value = root.get(key)
                if isinstance(value, CompoundTag):
                    seed = _tag_int(value.get("seed"))
                else:
                    seed = _tag_int(value)
                if seed is not None:
                    break

    return seed if seed is not None else 0


def build_level_dat(out_dir, world_name, seed, data_version, target_version):
    """重建完整 Java level.dat 并写回 ``out_dir/level.dat``。

    :param out_dir: 已转换的 Java Anvil 目录
    :param world_name: 世界展示名
    :param seed: 世界种子
    :param data_version: 目标 Java 版本的 DataVersion
    :param target_version: 目标版本元组（如 ``(1, 20, 4)``）
    """
    from amulet_nbt import (
        ByteTag,
        CompoundTag,
        DoubleTag,
        FloatTag,
        IntArrayTag,
        IntTag,
        ListTag,
        LongTag,
        ShortTag,
        StringTag,
    )

    if data_version is None:
        data_version = 3700
    if target_version is None:
        target_version = (1, 20, 4)
    seed = int(seed)

    Data = CompoundTag()
    Data["version"] = IntTag(LEGACY_WORLD_VERSION)
    Data["DataVersion"] = IntTag(int(data_version))
    Data["LevelName"] = StringTag(world_name)
    Data["LastPlayed"] = LongTag(int(time.time() * 1000))
    Data["RandomSeed"] = LongTag(seed)
    Data["GameType"] = IntTag(0)            # 生存
    Data["Difficulty"] = IntTag(2)          # 普通
    Data["DifficultyLocked"] = ByteTag(0)
    Data["initialized"] = ByteTag(1)
    Data["AllowCommands"] = ByteTag(1)
    Data["raining"] = ByteTag(0)
    Data["thundering"] = ByteTag(0)
    Data["rainTime"] = IntTag(0)
    Data["thunderTime"] = IntTag(0)
    Data["clearWeatherTime"] = IntTag(0)
    Data["Time"] = LongTag(0)
    Data["DayTime"] = LongTag(1000)

    # ---- 出生点 ----
    Data["SpawnX"] = IntTag(0)
    Data["SpawnY"] = IntTag(80)
    Data["SpawnZ"] = IntTag(0)
    Data["SpawnAngle"] = FloatTag(0.0)
    Data["SpawnForced"] = ByteTag(1)

    # ---- 玩家（最小合法结构；Java 首次打开时自行补全其余字段） ----
    player = CompoundTag()
    player["GameType"] = IntTag(0)
    player["Dimension"] = StringTag("minecraft:overworld")
    player["Pos"] = ListTag([DoubleTag(0.5), DoubleTag(80.0), DoubleTag(0.5)])
    player["Rotation"] = ListTag([FloatTag(0.0), FloatTag(0.0)])
    player["Motion"] = ListTag([DoubleTag(0.0), DoubleTag(0.0), DoubleTag(0.0)])
    player["SpawnX"] = IntTag(0)
    player["SpawnY"] = IntTag(80)
    player["SpawnZ"] = IntTag(0)
    player["SpawnAngle"] = FloatTag(0.0)
    player["SpawnForced"] = ByteTag(1)
    player["SelectedItemSlot"] = IntTag(0)
    player["SelectedItem"] = CompoundTag()
    player["Score"] = IntTag(0)
    player["Health"] = FloatTag(20.0)
    player["foodLevel"] = IntTag(20)
    player["foodSaturationLevel"] = FloatTag(5.0)
    player["foodExhaustionLevel"] = FloatTag(0.0)
    player["foodTickTimer"] = IntTag(0)
    player["Air"] = ShortTag(300)
    player["Fire"] = ShortTag(-20)
    player["OnGround"] = ByteTag(0)
    player["XpLevel"] = IntTag(0)
    player["XpP"] = FloatTag(0.0)
    player["XpSeed"] = IntTag(0)
    player["XpTotal"] = IntTag(0)
    abilities = CompoundTag()
    abilities["invulnerable"] = ByteTag(0)
    abilities["flying"] = ByteTag(0)
    abilities["mayfly"] = ByteTag(0)
    abilities["instabuild"] = ByteTag(0)
    abilities["mayBuild"] = ByteTag(1)
    abilities["flySpeed"] = FloatTag(0.05)
    abilities["walkSpeed"] = FloatTag(0.1)
    player["abilities"] = abilities
    Data["Player"] = player

    # ---- 世界边界 ----
    Data["BorderCenterX"] = DoubleTag(0.0)
    Data["BorderCenterZ"] = DoubleTag(0.0)
    Data["BorderSize"] = DoubleTag(60000000.0)
    Data["BorderSizeLerpTarget"] = DoubleTag(60000000.0)
    Data["BorderSafeZone"] = DoubleTag(5.0)
    Data["BorderWarningBlocks"] = DoubleTag(5.0)
    Data["BorderWarningTime"] = DoubleTag(15.0)
    Data["BorderSizeLerpTime"] = LongTag(0)
    Data["BorderDamagePerBlock"] = DoubleTag(0.2)

    # ---- WorldGenSettings（缺失会导致 Java 判存档损坏） ----
    def _gen_dimension(dimtype, settings, biome_type, biome_preset):
        biome = CompoundTag()
        biome["type"] = StringTag(biome_type)
        if biome_preset is not None:
            biome["preset"] = StringTag(biome_preset)
        generator = CompoundTag()
        generator["type"] = StringTag("minecraft:noise")
        generator["settings"] = StringTag(settings)
        generator["biome_source"] = biome
        dim = CompoundTag()
        dim["type"] = StringTag(dimtype)
        dim["generator"] = generator
        dim["seed"] = LongTag(seed)
        return dim

    dimensions = CompoundTag()
    dimensions["minecraft:overworld"] = _gen_dimension(
        "minecraft:overworld", "minecraft:overworld",
        "minecraft:multi_noise", "minecraft:overworld")
    dimensions["minecraft:the_nether"] = _gen_dimension(
        "minecraft:the_nether", "minecraft:nether",
        "minecraft:multi_noise", "minecraft:nether")
    dimensions["minecraft:the_end"] = _gen_dimension(
        "minecraft:the_end", "minecraft:end",
        "minecraft:the_end", None)

    wgs = CompoundTag()
    wgs["seed"] = LongTag(seed)
    wgs["features"] = ByteTag(1)
    wgs["bonus_chest"] = ByteTag(0)
    wgs["dimensions"] = dimensions
    Data["WorldGenSettings"] = wgs

    # ---- 数据包（保持空列表语义） ----
    data_packs = CompoundTag()
    data_packs["Enabled"] = ListTag([StringTag("vanilla")])
    data_packs["Disabled"] = ListTag([])
    Data["DataPacks"] = data_packs

    Data["LastOpenedWithVersion"] = IntArrayTag(list(target_version) + [0])

    root = CompoundTag()
    root["Data"] = Data

    path = os.path.join(out_dir, "level.dat")
    try:
        root.save_to(path, compressed=True)
    except Exception:
        root.save_to(path)