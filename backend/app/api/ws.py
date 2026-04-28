"""Celery-backed socket.io WebSocket bridge.

Client lifecycle:
    1. Client connects via socket.io at /ws
    2. Client emits "subscribe_simulation" with {"simulation_id": "<uuid>"}
    3. Server subscribes to Redis channel "simulation:{simulation_id}"
    4. Server forwards every Redis message as "sim_event" to the client
    5. On client disconnect, Redis subscription is cleaned up
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis
import socketio

from app.config import settings

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

# Maps sid → asyncio.Task so we can cancel on disconnect
_subscriber_tasks: dict[str, asyncio.Task] = {}


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    logger.debug("WS client connected: %s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    logger.debug("WS client disconnected: %s", sid)
    task = _subscriber_tasks.pop(sid, None)
    if task and not task.done():
        task.cancel()


@sio.event
async def subscribe_simulation(sid: str, data: dict) -> None:
    """Client subscribes to live events for a specific simulation."""
    simulation_id = (data or {}).get("simulation_id")
    if not simulation_id:
        await sio.emit("error", {"message": "simulation_id required"}, to=sid)
        return

    # Cancel any existing subscription for this client
    old_task = _subscriber_tasks.pop(sid, None)
    if old_task and not old_task.done():
        old_task.cancel()

    channel = f"simulation:{simulation_id}"
    task = asyncio.create_task(_forward_events(sid, channel))
    _subscriber_tasks[sid] = task
    logger.info("Client %s subscribed to %s", sid, channel)


async def _forward_events(sid: str, channel: str) -> None:
    """Subscribe to a Redis pub/sub channel and forward messages to the WS client."""
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        async with client.pubsub() as pubsub:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                await sio.emit("sim_event", data, to=sid)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Redis subscriber error for %s: %s", channel, exc)
    finally:
        _subscriber_tasks.pop(sid, None)
