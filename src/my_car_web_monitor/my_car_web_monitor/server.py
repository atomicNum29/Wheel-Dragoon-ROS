from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rclpy.node import Node

from my_car_web_monitor.config import Settings
from my_car_web_monitor.lidar import LidarStream
from my_car_web_monitor.control import RosControlBridge
from my_car_web_monitor.streams import StreamRegistry
from my_car_web_monitor.teleop import TeleopState

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web" / "static"


class OfferRequest(BaseModel):
    stream_id: str
    sdp: str
    type: str


def create_app(node: Node, settings: Settings) -> FastAPI:
    app = FastAPI(title="my_car_web_monitor")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    stream_registry: StreamRegistry | None = None
    control_bridge: RosControlBridge | None = None
    active_control_socket: WebSocket | None = None
    lidar_stream: LidarStream | None = None

    @app.on_event("startup")
    async def startup_event() -> None:
        nonlocal stream_registry, control_bridge, lidar_stream
        stream_registry = StreamRegistry(settings, node)
        control_bridge = RosControlBridge(node, settings)
        lidar_stream = LidarStream(node)

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        if lidar_stream is not None:
            lidar_stream.close()
        if control_bridge is not None:
            await control_bridge.stop()
        if stream_registry is not None:
            await stream_registry.close()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/time")
    async def server_time() -> JSONResponse:
        received = time.monotonic() * 1000
        return JSONResponse(
            {"received_ms": received, "sent_ms": time.monotonic() * 1000},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/streams")
    async def streams() -> dict[str, list[dict[str, str]]]:
        if stream_registry is None:
            raise HTTPException(status_code=503, detail="Stream registry is not ready")
        return {"streams": stream_registry.list_streams()}

    @app.post("/offer")
    async def offer(payload: OfferRequest) -> dict[str, str]:
        if stream_registry is None:
            raise HTTPException(status_code=503, detail="Stream registry is not ready")
        try:
            return await stream_registry.create_answer(
                payload.stream_id,
                {"sdp": payload.sdp, "type": payload.type},
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown stream '{payload.stream_id}'") from exc

    @app.get("/control/config")
    async def control_config() -> dict[str, float]:
        return {"linear_speed": 2.0, "steering_angle": 0.845, "angular_speed": 5.0,
                "ramp_seconds": settings.control_ramp_seconds,
                "mouse_return_seconds": settings.control_mouse_return_seconds}

    @app.get("/control/status")
    async def control_status() -> dict:
        if control_bridge is None:
            raise HTTPException(status_code=503, detail="ROS control bridge is not ready")
        return control_bridge.status()

    @app.websocket("/ws/status")
    async def status_ws(websocket: WebSocket) -> None:
        # Independent subscribers: no operator ownership and no stop commands.
        await websocket.accept()
        if control_bridge is None:
            await websocket.close(code=1011)
            return
        stream = control_bridge.status_stream
        client = stream.subscribe()

        async def send_statuses() -> None:
            while True:
                try:
                    snapshot = await asyncio.wait_for(client.queue.get(), timeout=1.0)
                    payload = {"type": "motor_status", **snapshot.payload(),
                               "stream_dropped_count": client.dropped}
                except TimeoutError:
                    payload = {"type": "status_heartbeat"}
                await asyncio.wait_for(websocket.send_json(payload), timeout=2.0)

        async def receive_disconnect() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                # This socket is read-only; incoming messages never control ROS.

        sender = asyncio.create_task(send_statuses())
        receiver = asyncio.create_task(receive_disconnect())
        try:
            done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, OSError):
            logger.info("Status websocket disconnected or send timed out")
        finally:
            stream.unsubscribe(client)
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            try:
                await websocket.close()
            except (RuntimeError, OSError):
                pass

    @app.websocket("/ws/scan")
    async def scan_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        if lidar_stream is None:
            await websocket.close(code=1011)
            return

        async def send_scans() -> None:
            revision = 0
            while True:
                revision, packet = lidar_stream.packet_after(revision)
                if packet is not None:
                    await asyncio.wait_for(websocket.send_bytes(packet), timeout=2.0)
                # Preserve every valid ray in a scan; skip old scans, never queue them.
                await asyncio.sleep(0.1)

        async def receive_disconnect() -> None:
            while True:
                if (await websocket.receive())["type"] == "websocket.disconnect":
                    return

        sender = asyncio.create_task(send_scans())
        receiver = asyncio.create_task(receive_disconnect())
        try:
            done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, OSError):
            logger.info("Scan websocket disconnected or send timed out")
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            try:
                await websocket.close()
            except (RuntimeError, OSError):
                pass

    @app.websocket("/ws/control")
    async def control_ws(websocket: WebSocket) -> None:
        nonlocal active_control_socket
        await websocket.accept()
        if control_bridge is None or active_control_socket is not None:
            await websocket.send_json({"type": "error", "message": "다른 제어 세션이 사용 중이거나 ROS가 준비되지 않았습니다"})
            await websocket.close(code=1008)
            return
        active_control_socket = websocket
        state = TeleopState(settings.control_ramp_seconds, settings.control_mouse_return_seconds)
        last_input = time.monotonic()
        feedback = {"message": "연결됨 · 새 입력을 시작하세요"}
        issued_tokens = {}
        token_seq = 0
        last_event = 0
        stop_marker = None
        previous_feedback = control_bridge.feedback()

        async def receive_inputs():
            nonlocal last_input, last_event
            while True:
                payload = await websocket.receive_json()
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                token = payload.get("token")
                if type(token) is not int or time.monotonic() - issued_tokens.get(token, -1e9) > settings.control_watchdog_timeout:
                    raise ValueError("오래된 제어 요청 · 다시 연결하세요")
                kind = payload.get("type")
                # Only fresh client heartbeats keep this controller alive.
                if kind == "heartbeat":
                    last_input = time.monotonic()
                    continue
                try:
                    event_id = payload.get("event_id")
                    if type(event_id) is not int or event_id <= last_event:
                        raise ValueError("잘못된 입력 순번")
                    if kind in ("input", "mode") and payload.get("input_epoch") != state.input_epoch:
                        feedback["message"] = "이전 입력은 폐기되었습니다 · 새로 조작하세요"
                    elif kind == "input":
                        accepted = state.input(payload.get("source"), payload.get("active"),
                            payload.get("x"), payload.get("y"), payload.get("steer_delta", 0))
                        feedback["message"] = "" if accepted else "현재 입력 방식 또는 정지 확인이 우선합니다"
                    elif kind == "mode":
                        if state.request_mode(payload.get("pivot")):
                            feedback["message"] = "정지 지령 확인 대기"
                        else:
                            feedback["message"] = "눌린 키·드래그 또는 진행 중인 전환이 우선합니다"
                    elif kind == "limits":
                        if not state.neutral:
                            feedback["message"] = "중립에서만 최대값을 변경할 수 있습니다"
                        else:
                            try:
                                state.set_limits([payload.get("linear"), payload.get("steering"), payload.get("angular")])
                                feedback["message"] = "최대값 적용됨"
                            except ValueError as error:
                                feedback["message"] = str(error)
                    elif kind == "stop":
                        # Normal stop uses the same return ramp and keeps ownership.
                        state.return_to_neutral()
                    elif kind == "estop":
                        control_bridge.estop = True
                        state.reset()
                    elif kind == "clear_estop":
                        if not state.neutral:
                            raise ValueError("중립에서 비상정지를 해제하세요")
                        control_bridge.estop = False
                        state.reset()
                    else:
                        raise ValueError("지원하지 않는 제어 요청")
                    last_event = event_id
                    last_input = time.monotonic()
                except (ValueError, TypeError) as error:
                    feedback["message"] = str(error)
                    # Invalid input ends the session instead of refreshing old motion.
                    raise ValueError(str(error)) from error

        async def transmit_targets():
            nonlocal token_seq, stop_marker, previous_feedback
            previous = time.monotonic()
            while True:
                now = time.monotonic()
                if now - last_input > settings.control_watchdog_timeout:
                    raise ValueError("입력 수신 만료 · 다시 연결하세요")
                current = control_bridge.feedback()
                # RC authority changes do not disconnect the web session. Real
                # telemetry loss or host/MCU session boundaries discard old input.
                if ((previous_feedback["fresh"] and not current["fresh"])
                        or current["identity"] != previous_feedback["identity"]):
                    state.suspend()
                    stop_marker = None
                previous_feedback = current
                if control_bridge.estop:
                    if state.owner is not None or state.switching or any(state.values):
                        state.reset()
                    stop_marker = None
                elif state.switching:
                    if not current["auto"]:
                        stop_marker = None
                    elif stop_marker is None:
                        # Record a baseline before publishing the OLD-mode stop.
                        stop_marker = (current["identity"], current["revision"])
                    elif (current["identity"] == stop_marker[0]
                          and current["revision"] > stop_marker[1]
                          and current["flags"] & 2048  # applied command valid
                          and current["flags"] & 16  # selected request valid
                          and bool(current["flags"] & 4096) == state.pivot
                          and current["requested"] == (0, 0, 0)
                          and current["applied_mode"] == (4 if state.pivot else 1)
                          and current["applied_v"] == 0 and current["applied_w"] == 0):
                        state.complete_mode()
                        stop_marker = None
                        feedback["message"] = "정지 지령 확인 · 모드 전환 완료"
                else:
                    stop_marker = None
                values = state.tick(now - previous)
                previous = now
                if current["auto"] and not control_bridge.estop:
                    outgoing = values
                    enabled = True
                else:
                    outgoing = [0.0, 0.0, 0.0]
                    enabled = False
                control_bridge.publish_command(outgoing, enable=enabled, pivot=state.pivot,
                                               identity=current["identity"])
                token_seq += 1
                issued_tokens[token_seq] = now
                for old_token, at in list(issued_tokens.items()):
                    if now - at > settings.control_watchdog_timeout:
                        del issued_tokens[old_token]
                await asyncio.wait_for(websocket.send_json({"type": "control_state", **state.snapshot(),
                    "token": token_seq, "last_event": last_event,
                    "estop": control_bridge.estop, "message": feedback["message"],
                    "authority": "control" if current["auto"] else "standby",
                    "telemetry_fresh": current["fresh"], "enabled": enabled,
                    "outgoing": outgoing,
                    "command_topic": settings.command_topic}), timeout=settings.control_watchdog_timeout)
                await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(receive_inputs()), asyncio.create_task(transmit_targets())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, OSError, ValueError, TimeoutError) as error:
            logger.info("Control session ended: %s", error)
            try:
                await asyncio.wait_for(websocket.send_json({"type": "error", "message": str(error)}), timeout=0.2)
            except (RuntimeError, OSError, TimeoutError):
                pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await control_bridge.stop()
            finally:
                # A failed ROS disable publication must not retain controller ownership.
                if active_control_socket is websocket:
                    active_control_socket = None
                try:
                    await websocket.close()
                except (RuntimeError, OSError):
                    pass

    return app
