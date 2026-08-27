"""Minimal pure-Python stand-in for the `rocksdb` CPython package.

Amulet-core uses RocksDB as an off-RAM snapshot cache for its undo/redo
history database (see amulet/api/level/base_level/base_level.py). It only
calls `put`, `get`, and `close` on the resulting object, so a plain dict
backed by a pickle file is a fully functional substitute for headless
conversion.

This module is registered into `sys.modules` under the top-level name
``rocksdb`` by ``backend/__init__.py`` before amulet is ever imported.
"""

import os
import pickle


class CompressionType:
    NoCompression = 0
    SnappyCompression = 1
    ZlibCompression = 2
    BZip2Compression = 3
    LZ4Compression = 4
    LZ4HCCompression = 5
    XpressCompression = 6
    ZstdCompression = 7


class Options:
    def __init__(self):
        self.create_if_missing = False
        self.error_if_exists = False
        self.compression_type = CompressionType.NoCompression
        self.compression = CompressionType.NoCompression
        self.prefix_extractor = None
        self.use_fsync = False


class WriteOptions:
    def __init__(self):
        self.sync = False
        self.disable_wal = True


class ReadOptions:
    def __init__(self):
        pass


class RocksDB:
    """A trivially small bytes->bytes store backed by memory + a pickle file."""

    def __init__(self, path, options=None, write_options=None, read_only=False):
        self.path = os.fspath(path)
        self._data = {}
        if not read_only:
            os.makedirs(self.path, exist_ok=True)
        self.read_only = read_only
        # try to restore a previously persisted store
        for name in ("db.pkl", "data.db", "history_db.pkl"):
            f = os.path.join(self.path, name)
            if os.path.exists(f):
                try:
                    with open(f, "rb") as fh:
                        self._data = pickle.load(fh)
                except Exception:
                    pass
                break

    def put(self, key, value, *args, **kwargs):
        if self.read_only:
            raise IOError("read-only")
        self._data[bytes(key)] = bytes(value)

    def get(self, key, *args, **kwargs):
        return self._data.get(bytes(key))

    def delete(self, key, *args, **kwargs):
        self._data.pop(bytes(key), None)

    def iterator(self, *args, **kwargs):
        return iter(sorted(self._data.items()))

    def get_snapshot(self):
        return None

    def release_snapshot(self, *args, **kwargs):
        pass

    def close(self, *args, **kwargs):
        try:
            with open(os.path.join(self.path, "db.pkl"), "wb") as fh:
                pickle.dump(dict(self._data), fh)
        except Exception:
            pass