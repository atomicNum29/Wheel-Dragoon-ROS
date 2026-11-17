"""20 Hz latest-value collection; never claims simultaneous measurements."""
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from my_car_interfaces.msg import WheelFeedback, VoltageFeedback, McuStatus, RobotTelemetry, LinkState

class TelemetryAggregator(Node):
    def __init__(self):
        super().__init__("telemetry_aggregator")
        self.clear()
        self.connected = False
        self.connection_id = None
        self.last_status_at = None
        self.create_subscription(LinkState, "/mcu_bridge_node/link_state", self.link,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(WheelFeedback, "/mcu_bridge_node/wheel_feedback", self.wheel, 100)
        self.create_subscription(VoltageFeedback, "/mcu_bridge_node/voltage_feedback", self.voltage, 100)
        self.create_subscription(McuStatus, "/mcu_bridge_node/mcu_status", self.status, 100)
        self.publisher = self.create_publisher(RobotTelemetry, "/telemetry", 10)
        self.create_timer(0.05, self.publish)

    def clear(self):
        self.wheels = [None] * 4
        self.drivers = [None] * 2
        self.current = None
        self.last_status_at = None

    def link(self, message):
        self.clear()
        self.connected = message.connected
        self.connection_id = message.connection_id

    def wheel(self, message):
        if self.connected and message.connection_id == self.connection_id and self.current is not None and message.wheel_id < 4:
            old = self.wheels[message.wheel_id]
            if old is None or 0 < ((message.seq - old[0].seq) & 65535) < 32768:
                self.wheels[message.wheel_id] = (message, time.monotonic())

    def voltage(self, message):
        if self.connected and message.connection_id == self.connection_id and self.current is not None and message.driver_id < 2:
            old = self.drivers[message.driver_id]
            if old is None or 0 < ((message.seq - old[0].seq) & 65535) < 32768:
                self.drivers[message.driver_id] = (message, time.monotonic())

    def status(self, message):
        if not self.connected or message.connection_id != self.connection_id:
            return
        now = time.monotonic()
        if self.current is not None:
            if message.session != self.current[0].session or now - self.current[1] > 1.0:
                self.clear()
            elif not 0 < ((message.seq - self.current[0].seq) & 65535) < 32768:
                return
        self.current = (message, now)

    def publish(self):
        now = time.monotonic()
        # A long status gap is a new local collection boundary, not proof of reboot.
        if self.current is not None and now - self.current[1] > 1.0:
            self.clear()
        result = RobotTelemetry(published_at=self.get_clock().now().to_msg(),
            status_present=self.current is not None, status_age_sec=-1.0)
        if self.current:
            result.status, at = self.current
            result.status_age_sec = now - at
        for values, messages, present, ages, cls in (
            (self.wheels, result.wheels, result.wheel_present, result.wheel_age_sec, WheelFeedback),
            (self.drivers, result.drivers, result.driver_present, result.driver_age_sec, VoltageFeedback)):
            for index, item in enumerate(values):
                messages[index] = item[0] if item else cls()
                present[index] = item is not None
                ages[index] = now - item[1] if item else -1.0
        self.publisher.publish(result)

def main(args=None):
    rclpy.init(args=args)
    node = TelemetryAggregator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
