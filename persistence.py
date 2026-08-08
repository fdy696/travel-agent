"""Agent thread persistence resources.

Conversation/checkpoint state 使用 Redis；Plan/Requirements 仍由 PlanningRepository 管理。
Redis checkpointer 是应用生命周期资源，不在 build_agent() 内部创建。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from config import get_settings


@asynccontextmanager
async def open_redis_checkpointer() -> AsyncIterator[AsyncRedisSaver]:
    settings = get_settings()

    ttl = None
    if settings.REDIS_CHECKPOINT_TTL_MINUTES is not None:
        ttl = {
            "default_ttl": float(settings.REDIS_CHECKPOINT_TTL_MINUTES),
            "refresh_on_read": settings.REDIS_CHECKPOINT_REFRESH_ON_READ,
        }

    # AsyncRedisSaver.from_conn_string() 的 async context manager 会在进入时
    # 自动执行 asetup() 创建所需 Redis Search indexes，并在退出时关闭连接。
    async with AsyncRedisSaver.from_conn_string(
        settings.REDIS_URL,
        ttl=ttl,
        checkpoint_prefix=settings.REDIS_CHECKPOINT_PREFIX,
        checkpoint_write_prefix=settings.REDIS_CHECKPOINT_WRITE_PREFIX,
    ) as checkpointer:
        yield checkpointer
