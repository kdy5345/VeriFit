from fastapi import APIRouter
from app.core.cache import get_cache
from app.core.config import settings


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/v1/cache/status")
def cache_status() -> dict:
    """Local-service diagnostics; never return prompts, keys or cached values."""
    cache = get_cache()
    with cache.guard:
        return {"enabled": settings.cache_enabled,
                "backend": "redis" if cache.redis is not None else "memory",
                "redis_cooldown": cache.redis is not None and cache.clock() < cache.unavailable_until,
                "counters": dict(cache.stats), "memory_entries": len(cache.memory),
                "memory_bytes": cache.memory_bytes}
