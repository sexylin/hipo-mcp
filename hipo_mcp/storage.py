"""可配置存储后端：Redis（可选）回落进程内内存。

用途：
  - OAuth 协议状态（client 注册 / auth_code / access_token / refresh_token /
    pending_auth）持久化到 Redis，支持多副本水平扩展；
  - 验证码发送限流桶持久化，多副本共享同一计数。

配置：
  设置环境变量 HIPO_REDIS_URL（如 redis://127.0.0.1:6379/0）启用 Redis；
  未设置或 redis-py 未安装时自动回落为进程内内存存储（单副本语义）。

  内存存储对单进程部署完全足够；水平扩展多副本时务必配置 Redis，
  否则 OAuth 状态与限流计数只对各自进程有效。
"""
from __future__ import annotations

import os
import pickle
import threading
import time
from typing import Any, Iterator, MutableMapping, Optional

REDIS_URL = os.environ.get("HIPO_REDIS_URL", "")

_redis_client: Any = None
_redis_lock = threading.Lock()


def _try_import_redis():
    try:
        import redis  # noqa: F401
        return True
    except ImportError:
        return False


def redis_enabled() -> bool:
    """是否启用 Redis 存储（配置了 URL 且 redis-py 可用）。"""
    if not REDIS_URL:
        return False
    if not _try_import_redis():
        print("WARN: HIPO_REDIS_URL 已配置但未安装 redis-py，回落进程内内存存储。")
        return False
    return True


def get_redis_client():
    """惰性单例 Redis 连接。"""
    global _redis_client
    if not REDIS_URL or not _try_import_redis():
        return None
    with _redis_lock:
        if _redis_client is None:
            import redis
            _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
        return _redis_client


# ────────────────────────────────────────────
# 内存存储（默认）
# ────────────────────────────────────────────

class MemoryStore:
    """进程内 KV 存储，支持 TTL。多线程安全。"""

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            exp = self._data.get(f"{key}:exp")
            if exp is not None and exp < time.time():
                self._data.pop(key, None)
                self._data.pop(f"{key}:exp", None)
                return default
            return self._data.get(key, default)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            self._data[key] = value
            if ttl is not None:
                self._data[f"{key}:exp"] = time.time() + ttl
            else:
                self._data.pop(f"{key}:exp", None)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._data.pop(f"{key}:exp", None)

    def incr(self, key: str, ttl: Optional[int] = None) -> int:
        with self._lock:
            now = time.time()
            exp = self._data.get(f"{key}:exp")
            if exp is not None and exp < now:
                self._data[key] = 0
                self._data.pop(f"{key}:exp", None)
            value = int(self._data.get(key, 0)) + 1
            self._data[key] = value
            if ttl is not None:
                self._data[f"{key}:exp"] = now + ttl
            return value


# ────────────────────────────────────────────
# Redis 存储（可选）
# ────────────────────────────────────────────

class RedisStore:
    """Redis KV 存储，值经 pickle 序列化（内部数据，非用户输入直接反序列化）。"""

    def __init__(self, client: Any):
        self._client = client

    def get(self, key: str, default: Any = None) -> Any:
        try:
            raw = self._client.get(key)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Redis get failed ({key}): {exc}")
            return default
        if raw is None:
            return default
        try:
            return pickle.loads(raw)
        except Exception:  # noqa: BLE001
            return default

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        raw = pickle.dumps(value)
        try:
            if ttl is not None:
                self._client.setex(key, ttl, raw)
            else:
                self._client.set(key, raw)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Redis set failed ({key}): {exc}")

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Redis delete failed ({key}): {exc}")

    def incr(self, key: str, ttl: Optional[int] = None) -> int:
        try:
            value = self._client.incr(key)
            if ttl is not None:
                self._client.expire(key, ttl)
            return int(value)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Redis incr failed ({key}): {exc}")
            return 0


class RedisDict(MutableMapping[str, Any]):
    """把 Redis 封装成 MutableMapping，用于替换 OAuth provider 的内存 dict。

    每个键对应 Redis 的一个 key；key 集合维护在 {prefix}:keys 的 Redis SET 中，
    以支持 __iter__ / __len__。
    """

    def __init__(self, prefix: str, store: RedisStore):
        self._prefix = prefix
        self._store = store
        self._keys_key = f"{prefix}:keys"

    def _key(self, k: str) -> str:
        return f"{self._prefix}:{k}"

    def __getitem__(self, k: str) -> Any:
        value = self._store.get(self._key(k))
        if value is None:
            raise KeyError(k)
        return value

    def __setitem__(self, k: str, v: Any) -> None:
        self._store.set(self._key(k), v)
        try:
            self._store._client.sadd(self._keys_key, k)
        except Exception:  # noqa: BLE001
            pass

    def __delitem__(self, k: str) -> None:
        if not self._store.get(self._key(k)):
            raise KeyError(k)
        self._store.delete(self._key(k))
        try:
            self._store._client.srem(self._keys_key, k)
        except Exception:  # noqa: BLE001
            pass

    def __iter__(self) -> Iterator[str]:
        try:
            return iter(self._store._client.smembers(self._keys_key))
        except Exception:  # noqa: BLE001
            return iter(())

    def __len__(self) -> int:
        try:
            return int(self._store._client.scard(self._keys_key))
        except Exception:  # noqa: BLE001
            return 0

    def get(self, k: str, default: Any = None) -> Any:
        try:
            return self[k]
        except KeyError:
            return default


class _Store:
    """进程级单例：按配置选择 MemoryStore 或 RedisStore。"""

    def __init__(self):
        self.redis_enabled = redis_enabled()
        if self.redis_enabled:
            self._store: Any = RedisStore(get_redis_client())
        else:
            self._store = MemoryStore()

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._store.set(key, value, ttl)

    def delete(self, key: str) -> None:
        self._store.delete(key)

    def incr(self, key: str, ttl: Optional[int] = None) -> int:
        return self._store.incr(key, ttl)

    def redis_dict(self, prefix: str) -> MutableMapping[str, Any]:
        if self.redis_enabled:
            return RedisDict(prefix, self._store)
        return {}


STORE = _Store()