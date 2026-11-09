"""Names of the API's cache entries in Redis, shared by the API and the model registry."""

import logging

import redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

CACHE_PREFIX = "cache:"
# What changes when a new champion is promoted (ADR 0008: model info is cleared on promotion)
MODEL_PATHS = ("/v1/model", "/v1/accuracy")


def clear_model_cache(redis_url: str) -> int:
    """Forget cached model and accuracy answers. Returns how many entries were removed."""
    try:
        client = redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
        keys = [key for path in MODEL_PATHS for key in client.scan_iter(f"{CACHE_PREFIX}{path}*")]
        return int(client.delete(*keys)) if keys else 0
    except RedisError:
        # Not fatal: the entries expire within an hour anyway
        logger.warning("Could not clear the API cache; /v1/model updates within an hour")
        return 0
