"""Bounded JSON cache: Redis in Compose, memory locally; failures never block work."""

import hashlib
import json
import logging
import time
from collections import Counter, OrderedDict
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Callable, TypeVar

from pydantic import TypeAdapter, ValidationError
from redis import Redis
from redis.exceptions import RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import settings

T = TypeVar("T")
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def code_version() -> str:
    # Prompt, schema and calculation changes cannot reuse previous code's results.
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class JsonCache:
    def __init__(self, redis_client=None, clock=time.monotonic):
        self.redis = redis_client
        self.clock = clock
        self.memory = OrderedDict()
        self.memory_bytes = 0
        self.guard = RLock()
        self.locks = {}
        self.stats = Counter()
        self.unavailable_until = 0.0

    def count(self, namespace, event):
        with self.guard:
            self.stats[f"{namespace}.{event}"] += 1

    def _redis_ready(self):
        return self.redis is not None and self.clock() >= self.unavailable_until

    def _unavailable(self):
        # No retry storm and no URL, API key, prompt or user data in logs.
        with self.guard:
            self.unavailable_until = self.clock() + 5
            self.stats["redis.error"] += 1
        logger.warning("Redis cache unavailable; continuing with bounded memory cache")

    def get(self, key):
        if self._redis_ready():
            try:
                value = self.redis.get(key)
                # A Redis miss is authoritative: do not resurrect an older memory entry.
                return value
            except RedisError:
                self._unavailable()
        with self.guard:
            item = self.memory.get(key)
            if item is None:
                return None
            deadline, value = item
            if deadline <= self.clock():
                self._remove(key)
                return None
            self.memory.move_to_end(key)
            return value

    def _remove(self, key):
        item = self.memory.pop(key, None)
        if item:
            self.memory_bytes -= len(item[1])

    def delete(self, key):
        if self._redis_ready():
            try:
                self.redis.delete(key)
            except RedisError:
                self._unavailable()
        with self.guard:
            self._remove(key)

    def put(self, key, value, ttl):
        if ttl <= 0 or len(value) > settings.cache_max_value_bytes:
            return False
        if self._redis_ready():
            try:
                self.redis.set(key, value, ex=ttl)
                return True
            except RedisError:
                self._unavailable()
        with self.guard:
            for expired_key, (deadline, _) in list(self.memory.items()):
                if deadline <= self.clock():
                    self._remove(expired_key)
            self._remove(key)
            if settings.cache_max_entries <= 0 or len(value) > settings.cache_memory_max_bytes:
                return False
            self.memory[key] = (self.clock() + ttl, value)
            self.memory_bytes += len(value)
            while len(self.memory) > settings.cache_max_entries or self.memory_bytes > settings.cache_memory_max_bytes:
                self._remove(next(iter(self.memory)))
            return key in self.memory

    def remember(self, namespace: str, payload, adapter: TypeAdapter[T],
                 compute: Callable[[], T], ttl: int, cacheable: Callable[[T], bool] = lambda _: True) -> T:
        if not settings.cache_enabled or ttl <= 0:
            return compute()
        try:
            key = f"{settings.cache_prefix}:{code_version()}:{namespace}:{fingerprint(payload)}"
        except (ValueError, TypeError, OSError):
            self.count(namespace, "bypass")
            return compute()
        # Single-flight within the current single API process.
        with self.guard:
            locks = self.locks.get(namespace)
            if locks is None:
                locks = self.locks[namespace] = [RLock() for _ in range(64)]
            lock = locks[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(locks)]
        with lock:
            raw = self.get(key)
            if raw is not None:
                try:
                    result = adapter.validate_json(raw)
                    self.count(namespace, "hit")
                    return result
                except (ValidationError, ValueError, TypeError):
                    self.count(namespace, "invalid")
                    self.delete(key)
            self.count(namespace, "miss")
            result = compute()  # Exceptions are not stored.
            if cacheable(result):
                raw = adapter.dump_json(result)
                if len(raw) <= settings.cache_max_value_bytes:
                    if self.put(key, raw, ttl):
                        self.count(namespace, "store")
            return result


@lru_cache(maxsize=1)
def get_cache() -> JsonCache:
    client = None
    if settings.redis_url:
        try:
            client = Redis.from_url(settings.redis_url.get_secret_value(),
                                    socket_connect_timeout=settings.cache_redis_timeout_seconds,
                                    socket_timeout=settings.cache_redis_timeout_seconds,
                                    retry=Retry(NoBackoff(), 0), max_connections=32)
        except (ValueError, RedisError):
            logger.warning("Invalid Redis configuration; using bounded memory cache")
    return JsonCache(client)


def cached(namespace, payload, model, compute, ttl, cacheable=lambda _: True):
    return get_cache().remember(namespace, payload, TypeAdapter(model), compute, ttl, cacheable)
