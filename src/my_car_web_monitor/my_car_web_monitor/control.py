from __future__ import annotations

import threading
import time
from typing import Any

from rclpy.node import Node
import json
from my_car_interfaces.msg import RobotTelemetry, MotionCommand, McuStatus
from rosidl_runtime_py.convert import message_to_ordereddict

from my_car_web_monitor.config import Settings
from my_car_web_monitor.status_stream import StatusStream


class RosControlBridge:
    """Typed feedback and direct v/theta or PIVOT command publication."""

    def __init__(self, node: Node, settings: Settings) -> None:
        self._node = node
        self._settings = settings
        self._publisher = node.create_publisher(MotionCommand, settings.command_topic, 1)
        self._lock = threading.Lock()
        self._telemetry_at = None
        self._telemetry_identity = None
        self._telemetry_message = None
        self._feedback_revision = 0
        self._feedback_key = None
        self.estop = False
        self._has_output = False
        self._reported_estop = False
        self._last_command = {"linear": 0.0, "angular": 0.0, "age_sec": None}
        self._last_command_time: float | None = None
        self.status_stream = StatusStream()
        self._status_sub = node.create_subscription(
            RobotTelemetry,
            settings.motor_status_topic,
            self._on_motor_status,
            10,
        )

    def feedback(self):
        """Snapshot fresh MCU authority and commanded output, not physical stop."""
        with self._lock:
            fresh = (self._telemetry_at is not None and
                     time.monotonic() - self._telemetry_at <= self._settings.control_watchdog_timeout)
            status = self._telemetry_message
            return {
                "fresh": fresh, "identity": self._telemetry_identity,
                "revision": self._feedback_revision,
                "auto": bool(fresh and status is not None and status.mode == McuStatus.MODE_AUTO
                             and not status.flags & (
                                 McuStatus.FLAG_DRIVER_POWERDOWN | McuStatus.FLAG_DRIVER_STARTING)),
                "control_signal_estop": bool(fresh and status is not None
                                             and self.control_signal_estop(status)),
                "flags": status.flags if status is not None else 0,
                "applied_mode": status.applied_mode if status is not None else 255,
                "applied_v": status.applied_v_milli if status is not None else None,
                "applied_w": status.applied_w_milli if status is not None else None,
                "requested": ((status.requested_v_milli, status.requested_theta_milli,
                               status.requested_w_milli) if status is not None else None),
            }

    @staticmethod
    def control_signal_estop(status):
        """Identify only combinations reported by the MCU's latched recovery path."""
        if status.mode == McuStatus.MODE_FAILSAFE:
            return True
        required = McuStatus.FLAG_ESTOP_ACTIVE | McuStatus.FLAG_DRIVER_POWERDOWN
        return (status.mode == McuStatus.MODE_POWERDOWN
                and status.state == McuStatus.STATE_ESTOP
                and (status.flags & required) == required)

    def publish_command(self, values, *, enable, pivot=False, identity=None):
        if identity is None:
            with self._lock:
                identity = self._telemetry_identity
        if identity is None:
            identity = (0, 0)
            values, enable = [0.0, 0.0, 0.0], False
        message = MotionCommand(stamp=self._node.get_clock().now().to_msg(),
            connection_id=identity[0], session=identity[1],
            enable=enable, estop=self.estop, pivot=pivot,
            linear_velocity=float(values[0]), steering_angle=float(values[1]),
            angular_velocity=float(values[2]))
        self._publisher.publish(message)
        self._has_output = True
        self._last_command = {"linear": values[0], "steering": values[1], "angular": values[2],
                              "enable": enable, "pivot": pivot, "estop": self.estop}
        self._last_command_time = time.monotonic()

    async def stop(self):
        if self._has_output:
            self.publish_command([0.0, 0.0, 0.0], enable=False)
            self._has_output = False

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        command = dict(self._last_command)
        if self._last_command_time is not None:
            command["age_sec"] = round(now - self._last_command_time, 3)

        return {
            "command_topic": self._settings.command_topic,
            "motor_status_topic": self._settings.motor_status_topic,
            "last_command": command,
            **self.status_stream.latest_payload(),
        }

    def _on_motor_status(self, message: RobotTelemetry) -> None:
        with self._lock:
            self._telemetry_at = (time.monotonic() - message.status_age_sec
                if message.status_present and message.status_age_sec >= 0 else None)
            if message.status_present:
                key = (message.status.connection_id, message.status.session, message.status.seq)
                if key != self._feedback_key:
                    self._feedback_key = key
                    self._feedback_revision += 1
                self._telemetry_identity = (message.status.connection_id, message.status.session)
                self._telemetry_message = message.status
                # MCU failsafe recovery is physical POWERDOWN -> STOP. Do not
                # turn that shared ESTOP_ACTIVE bit into a sticky host estop.
                reported_estop = (message.status.mode == McuStatus.MODE_AUTO
                                  and bool(message.status.flags & McuStatus.FLAG_ESTOP_ACTIVE)
                                  and not self.control_signal_estop(message.status))
                if reported_estop and not self._reported_estop:
                    self.estop = True
                self._reported_estop = reported_estop
        value = message_to_ordereddict(message)
        status = value["status"]
        # Web JSON is produced only at this browser boundary.
        status.update(version=1, schema="split_v1", status_present=value["status_present"],
                      status_age_sec=value["status_age_sec"])
        status["control_signal_estop"] = bool(message.status_present
                                             and self.control_signal_estop(message.status))
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

