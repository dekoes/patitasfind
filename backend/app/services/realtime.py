"""Hub de chat en tiempo real.

Con REDIS_URL cada proceso (worker de uvicorn) se suscribe al patrón "chat:*" en Redis y
reparte los eventos a sus sockets locales; publicar desde cualquier worker (o desde un
endpoint REST síncrono) llega a todos. Sin Redis, todo ocurre dentro del proceso.
"""
import asyncio
import json
import logging

from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger(__name__)
CHANNEL_PREFIX = "chat:"
SEND_TIMEOUT_SECONDS = 5  # un socket que no recibe en este tiempo se considera muerto


class ChatHub:
    def __init__(self):
        self.local: dict[int, set[WebSocket]] = {}
        self._listener: asyncio.Task | None = None
        self._redis = None
        self._ready: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing: set[asyncio.Task] = set()  # cierres en curso (referencia para que no se pierdan)

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # Nuevo event loop (p. ej. pruebas o recarga): los clientes previos no sirven
            self._loop = loop
            self._listener = None
            self._redis = None

    # ---------------------------------------------------------------- conexión
    async def prepare(self):
        """Asegura la suscripción a Redis ANTES de aceptar el socket (evita perder mensajes)."""
        self._check_loop()
        if settings.redis_url:
            await self._ensure_listener()

    async def connect(self, conversation_id: int, websocket: WebSocket):
        await self.prepare()
        self.local.setdefault(conversation_id, set()).add(websocket)

    def disconnect(self, conversation_id: int, websocket: WebSocket):
        sockets = self.local.get(conversation_id)
        if sockets is not None:
            sockets.discard(websocket)
            if not sockets:
                self.local.pop(conversation_id, None)

    async def deliver_local(self, conversation_id: int, event: dict, exclude: WebSocket | None = None):
        """Envía a todos los sockets locales en paralelo; uno lento o roto no frena a los demás."""
        targets = [ws for ws in list(self.local.get(conversation_id, ())) if ws is not exclude]
        if targets:
            await asyncio.gather(*(self._send(conversation_id, ws, event) for ws in targets))

    async def _send(self, conversation_id: int, ws: WebSocket, event: dict) -> bool:
        try:
            await asyncio.wait_for(ws.send_json(event), timeout=SEND_TIMEOUT_SECONDS)
            return True
        except Exception:  # noqa: BLE001 - socket muerto o lento: se suelta y se cierra (el cliente reconecta)
            self.disconnect(conversation_id, ws)
            task = asyncio.create_task(self._close_quietly(ws))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)
            return False

    @staticmethod
    async def _close_quietly(ws: WebSocket):
        try:
            await asyncio.wait_for(ws.close(code=1011), timeout=1)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- publicación
    async def publish(self, conversation_id: int, event: dict, exclude: WebSocket | None = None):
        if settings.redis_url:
            try:
                self._check_loop()
                r = await self._get_async_redis()
                await r.publish(f"{CHANNEL_PREFIX}{conversation_id}", json.dumps(event, default=str))
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis pub/sub no disponible (%s); entrega local.", exc)
        await self.deliver_local(conversation_id, event, exclude=exclude)

    def publish_sync(self, conversation_id: int, event: dict):
        """Para código síncrono (endpoints REST en threadpool, tareas Celery).

        Usa el cliente de Redis compartido del proceso (pool de conexiones) en vez de abrir uno por mensaje.
        """
        if settings.redis_url:
            from app import cache

            client = cache._get_redis()
            if client is not None:
                try:
                    client.publish(f"{CHANNEL_PREFIX}{conversation_id}", json.dumps(event, default=str))
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("No se pudo publicar en Redis: %s", exc)
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.deliver_local(conversation_id, event), self._loop)

    # ---------------------------------------------------------------- Redis
    async def _get_async_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def _ensure_listener(self):
        if self._listener and not self._listener.done():
            return
        self._ready = asyncio.Event()
        self._listener = asyncio.create_task(self._listen())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=3)
        except asyncio.TimeoutError:
            logger.warning("La suscripción a Redis tardó demasiado.")

    async def _listen(self):
        while True:
            try:
                r = await self._get_async_redis()
                pubsub = r.pubsub()
                await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
                self._ready.set()
                async for msg in pubsub.listen():
                    if msg.get("type") != "pmessage":
                        continue
                    try:
                        conversation_id = int(str(msg["channel"])[len(CHANNEL_PREFIX):])
                        event = json.loads(msg["data"])
                    except (ValueError, TypeError):
                        continue
                    await self.deliver_local(conversation_id, event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Listener de Redis caído (%s); reintentando en 2 s.", exc)
                self._redis = None
                await asyncio.sleep(2)

    async def shutdown(self):
        if self._listener:
            self._listener.cancel()
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass


hub = ChatHub()
