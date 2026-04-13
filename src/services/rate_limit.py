from datetime import datetime, timedelta, timezone

import redis
from fastapi import HTTPException

from src.config.index import app_config


# Shared Redis client for API process rate-limiting checks.
redis_client = redis.Redis.from_url(app_config["redis_url"], decode_responses=True)


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date()
    next_midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc)
    return max(int((next_midnight - now).total_seconds()), 1)


def _get_daily_quota_key(clerk_id: str) -> str:
    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"rate_limit:messages:{clerk_id}:{today_key}"


def get_daily_message_quota(clerk_id: str, daily_limit: int = 20) -> dict:
    """Return current daily quota state for a user."""
    redis_key = _get_daily_quota_key(clerk_id)
    raw_count = redis_client.get(redis_key)
    used = int(raw_count) if raw_count else 0
    remaining = max(daily_limit - used, 0)

    ttl_seconds = redis_client.ttl(redis_key)
    if ttl_seconds is None or ttl_seconds < 0:
        ttl_seconds = _seconds_until_utc_midnight()

    return {
        "limit": daily_limit,
        "used": used,
        "remaining": remaining,
        "reset_in_seconds": ttl_seconds,
    }


def enforce_daily_message_limit(clerk_id: str, daily_limit: int = 20) -> dict:
    """
    Enforce a per-user, per-day message cap.

    Uses a Redis counter with key scope: user + UTC date.
    """
    redis_key = _get_daily_quota_key(clerk_id)

    try:
        current_count = redis_client.incr(redis_key)

        # Set expiry only when key is first created.
        if current_count == 1:
            redis_client.expire(redis_key, _seconds_until_utc_midnight())

        ttl_seconds = redis_client.ttl(redis_key)
        if ttl_seconds is None or ttl_seconds < 0:
            ttl_seconds = _seconds_until_utc_midnight()

        if current_count > daily_limit:
            retry_after = max(ttl_seconds, 60)
            raise HTTPException(
                status_code=429,
                detail=f"Daily message limit reached ({daily_limit}/day). Try again tomorrow.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(daily_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Used": str(current_count),
                },
            )

        return {
            "limit": daily_limit,
            "used": current_count,
            "remaining": max(daily_limit - current_count, 0),
            "reset_in_seconds": ttl_seconds,
        }
    except HTTPException:
        raise
    except Exception as e:
        # Fail closed to protect API keys if limiter infra is unavailable.
        raise HTTPException(
            status_code=503,
            detail=f"Rate limiter unavailable. Please retry shortly. Reason: {str(e)}",
        )