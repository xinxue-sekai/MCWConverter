# -*- coding: utf-8 -*-
"""网易基岩版存档 XOR 解密。

算法来源：NetEaseMC-Decryptor（GPL-3.0）。precision 复刻 conversion/decrypt.py。

加密格式（经真实网易存档验证）：
  - 每个被加密文件前 4 字节为魔数 ``80 1D 30 01``；
  - 魔数之后的正文与密钥流逐字节异或；
  - 不带魔数头的文件保持明文（LOG / 锁文件等）。

密钥推导（已知明文攻击）：
  LevelDB 规范规定 CURRENT 文件明文恒为 ``MANIFEST-<数字>\\n``，
  因此 key = xor(CURRENT[4:], MANIFEST名 + b"\\n")；16 字节密钥若前后两半
  相同则收敛为 8 字节周期密钥。

全程在**副本目录**上操作，绝不修改用户原始存档。
"""

import os
import shutil
import tempfile

#: 网易加密魔数（文件头 4 字节）
MAGIC = bytes([0x80, 0x1D, 0x30, 0x01])


def xor_bytes(data, key):
    """循环密钥异或。"""
    if not key:
        raise ValueError("empty xor key")
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def optimize_key(key):
    """16 字节密钥前后两半相同 -> 收敛为 8 字节。"""
    if len(key) == 16 and key[:8] == key[8:16]:
        return key[:8]
    return key


def find_manifest_name(db_dir):
    """在 db 目录中定位 MANIFEST 文件名（字典序首个，与 LevelDB 习惯一致）。"""
    names = sorted(
        n
        for n in os.listdir(db_dir)
        if n.startswith("MANIFEST") and os.path.isfile(os.path.join(db_dir, n))
    )
    if not names:
        raise FileNotFoundError(f"db 目录中未找到 MANIFEST 文件: {db_dir}")
    return names[0]


def derive_key(db_dir):
    """由加密的 CURRENT + MANIFEST 文件名推导密钥。

    :return: (key: bytes, manifest_name: str)
    :raises ValueError: CURRENT 头与魔数不匹配（非网易加密或未知加密）
    """
    manifest_name = find_manifest_name(db_dir)
    cur_path = os.path.join(db_dir, "CURRENT")
    if not os.path.isfile(cur_path):
        raise FileNotFoundError(f"db 目录中未找到 CURRENT 文件: {db_dir}")

    with open(cur_path, "rb") as fh:
        current = fh.read()
    if len(current) < 4 or current[:4] != MAGIC:
        raise ValueError("CURRENT 文件头与魔数不匹配：存档未加密或使用其他加密方案")

    source = manifest_name.encode("utf-8") + b"\n"
    key = optimize_key(xor_bytes(current[4:], source))
    return key, manifest_name


def decrypt_db(db_dir, progress_cb=None):
    """对 db 目录执行原地解密（仅处理带魔数头的文件）。

    :param progress_cb: 形如 ``fn(done: int, total: int)`` 的文件级进度回调
    :return: {"decrypted": n, "kept": m, "key_hex": str, "manifest": str}
    """
    key, manifest_name = derive_key(db_dir)

    files = [n for n in os.listdir(db_dir) if os.path.isfile(os.path.join(db_dir, n))]
    total = len(files)
    decrypted = 0
    kept = 0
    for i, name in enumerate(files):
        fp = os.path.join(db_dir, name)
        with open(fp, "rb") as fh:
            data = fh.read()
        if len(data) >= 4 and data[:4] == MAGIC:
            with open(fp, "wb") as fh:
                fh.write(xor_bytes(data[4:], key))
            decrypted += 1
        else:
            kept += 1
        if progress_cb is not None:
            progress_cb(i + 1, total)

    # 黄金校验：CURRENT 解密后必须精确等于 MANIFEST-<文件名>\n
    cur_path = os.path.join(db_dir, "CURRENT")
    with open(cur_path, "rb") as fh:
        plain_current = fh.read()
    if plain_current != manifest_name.encode("utf-8") + b"\n":
        raise ValueError("密钥自校验失败：CURRENT 解密结果与 LevelDB 规范不符")

    return {
        "decrypted": decrypted,
        "kept": kept,
        "key_hex": key.hex(),
        "manifest": manifest_name,
    }


def decrypt(src_folder, dst_folder=None, progress_cb=None, report=None):
    """把源存档复制到副本目录并解密。

    绝不修改 ``src_folder``。若副本中不存在加密的 db（或 db 无 CURRENT），
    则仅复制、不解密，原样返回副本目录（调用方仍可对明文 LevelDB 正常转换）。

    :param src_folder: 网易加密存档目录
    :param dst_folder: 副本目录；None 时自动创建临时目录
    :param progress_cb: ``fn(done: int, total: int)`` 文件级进度回调（仅解密阶段触发）
    :param report: 可选的 dict，解密发生时被原地填充
        ``{decrypted, kept, key_hex, manifest}``
    :return: 副本目录绝对路径（已解密或原本即明文）
    """
    src_folder = os.path.abspath(src_folder)
    if not os.path.isdir(src_folder):
        raise FileNotFoundError(f"源存档目录不存在: {src_folder}")

    if dst_folder is None:
        dst_folder = tempfile.mkdtemp(prefix="mcwc_dec_")
    else:
        dst_folder = os.path.abspath(dst_folder)
        if os.path.exists(dst_folder):
            shutil.rmtree(dst_folder)
    os.makedirs(dst_folder, exist_ok=True)

    # 整目录复制到副本
    for name in os.listdir(src_folder):
        s = os.path.join(src_folder, name)
        d = os.path.join(dst_folder, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)

    db_dir = os.path.join(dst_folder, "db")
    cur_path = os.path.join(db_dir, "CURRENT")
    if os.path.isdir(db_dir) and os.path.isfile(cur_path):
        with open(cur_path, "rb") as fh:
            head = fh.read(4)
        if head == MAGIC:
            result = decrypt_db(db_dir, progress_cb=progress_cb)
            if report is not None:
                report.update(result)

    return dst_folder