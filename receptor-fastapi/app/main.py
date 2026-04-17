from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import ReceiverConfig, load_config
from .dynamic_csv import DynamicCsvWriter
from .logging_utils import setup_logging
from .xbee_worker import XBeeReceiverWorker


class WebSocketManager:
    def __init__(self, logger) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.logger = logger

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        self.logger.info("WS cliente conectado, total=%s", len(self._clients))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        self.logger.info("WS cliente desconectado, total=%s", len(self._clients))

    async def broadcast(self, payload: dict[str, float | int]) -> None:
        stale_clients: list[WebSocket] = []

        async with self._lock:
            clients = list(self._clients)

        for client in clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale_clients.append(client)

        if stale_clients:
            async with self._lock:
                for client in stale_clients:
                    self._clients.discard(client)


logger = setup_logging("receptor.fastapi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: ReceiverConfig = load_config()

    cfg.received_dir.mkdir(parents=True, exist_ok=True)
    cfg.telemetry_csv_path.parent.mkdir(parents=True, exist_ok=True)

    ws_manager = WebSocketManager(logger)
    csv_writer = DynamicCsvWriter(cfg.telemetry_csv_path)

    loop = asyncio.get_running_loop()

    def on_telemetry(telemetry: dict[str, float | int]) -> None:
        t0 = time.perf_counter()
        csv_writer.append(telemetry)
        store_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("telemetry_store_ms=%.2f", store_ms)

        telemetry_copy = dict(telemetry)

        def _schedule_broadcast() -> None:
            asyncio.create_task(ws_manager.broadcast(telemetry_copy))

        loop.call_soon_threadsafe(_schedule_broadcast)

    def on_image(image_id: int, image_data: bytes) -> None:
        if not cfg.enable_image_transmission:
            return

        t0 = time.perf_counter()
        output_path = cfg.received_dir / f"received_{image_id:04d}_{int(time.time() * 1000)}.jpg"
        output_path.write_bytes(image_data)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "image_saved path=%s size=%sB elapsed_ms=%.2f",
            output_path,
            len(image_data),
            elapsed_ms,
        )

    worker = XBeeReceiverWorker(
        serial_port=cfg.serial_port,
        baudrate=cfg.baudrate,
        timeout_s=cfg.serial_timeout_s,
        enable_image_transmission=cfg.enable_image_transmission,
        telemetry_callback=on_telemetry,
        image_callback=on_image,
        logger=logger,
    )

    app.state.cfg = cfg
    app.state.ws_manager = ws_manager
    app.state.worker = worker

    logger.info("Receptor iniciado ENABLE_IMAGE_TRANSMISSION=%s", cfg.enable_image_transmission)
    worker.start()

    try:
        yield
    finally:
        worker.stop()
        logger.info("Receptor detenido")


app = FastAPI(title="CanSat Receiver", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str | int | bool]:
    cfg: ReceiverConfig = app.state.cfg
    return {
        "status": "ok",
        "enable_image_transmission": cfg.enable_image_transmission,
        "baudrate": cfg.baudrate,
        "serial_port": cfg.serial_port,
    }


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "CanSat receiver running"}


async def _telemetry_ws_handler(websocket: WebSocket) -> None:
    manager: WebSocketManager = app.state.ws_manager
    await manager.connect(websocket)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket) -> None:
    await _telemetry_ws_handler(websocket)


@app.websocket("/ws")
async def telemetry_ws_compat(websocket: WebSocket) -> None:
    await _telemetry_ws_handler(websocket)
