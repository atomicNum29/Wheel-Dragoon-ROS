from __future__ import annotations

import asyncio
import time
from typing import Any

from rclpy.node import Node
import json
from my_car_interfaces.msg import RobotTelemetry
from rosidl_runtime_py.convert import message_to_ordereddict

from my_car_web_monitor.config import Settings
from my_car_web_monitor.status_stream import StatusStream


class RosControlBridge:
    """Typed feedback subscription and browser JSON conversion; no driving output."""

    def __init__(self, node: Node, settings: Settings) -> None:
        self._node = node
        self._settings = settings
        self._publisher = None  # Feedback-only scope: no command publisher.
        self._lock = asyncio.Lock()
        self._last_command = {"linear": 0.0, "angular": 0.0, "age_sec": None}
        self._last_command_time: float | None = None
        self.status_stream = StatusStream()
        self._status_sub = node.create_subscription(
            RobotTelemetry,
            settings.motor_status_topic,
            self._on_motor_status,
            10,
        )

    async def send_command(self, linear: float, angular: float) -> dict[str, Any]:
        raise RuntimeError("Web driving control is disabled in feedback-only mode")

    async def stop(self) -> dict[str, Any]:
        return await self.send_command(0.0, 0.0)

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        command = dict(self._last_command)
        if self._last_command_time is not None:
            command["age_sec"] = round(now - self._last_command_time, 3)

        return {
            "cmd_vel_topic": self._settings.cmd_vel_topic,
            "motor_status_topic": self._settings.motor_status_topic,
            "last_command": command,
            **self.status_stream.latest_payload(),
        }

    def _on_motor_status(self, message: RobotTelemetry) -> None:
        value = message_to_ordereddict(message)
        status = value["status"]
        # Web JSON is produced only at this browser boundary.
        status.update(version=1, schema="split_v1", status_present=value["status_present"],
                      status_age_sec=value["status_age_sec"])
        status["wheels"] = {
            name: {**value["wheels"][idx], "present": value["wheel_present"][idx],
                   "age_sec": value["wheel_age_sec"][idx],
                   "valid": value["wheel_present"][idx] and 0 <= value["wheel_age_sec"][idx] <= 1.0
                            and bool(status["validity"] & (1 << idx))}
            for idx, name in enumerate(("lf", "rf", "lr", "rr"))}
        status["drivers"] = {
            name: {**value["drivers"][idx], "present": value["driver_present"][idx],
                   "age_sec": value["driver_age_sec"][idx],
                   "valid": value["driver_present"][idx] and 0 <= value["driver_age_sec"][idx] <= 3.0
                            and bool(status["validity"] & (1 << (idx + 4)))}
            for idx, name in enumerate(("a", "b"))}
        self.status_stream.publish(json.dumps(status))

    @staticmethod
    def _clamp(value: float, limit: float) -> float:
        limit = abs(float(limit))
        return max(-limit, min(limit, float(value)))

