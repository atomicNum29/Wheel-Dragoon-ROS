"""Receive-only MCU bridge: one validated packet produces one typed message."""
import math
import time
import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor
from my_car_interfaces.msg import WheelFeedback, VoltageFeedback, McuStatus, LinkState
from my_car_mcu_bridge.protocol import try_parse_packet
from my_car_mcu_bridge.serial_transport import SerialTransport

class McuBridgeNode(Node):
    def __init__(self):
        super().__init__("mcu_bridge_node")
        defaults = {"port": "/dev/ttyACM0", "baudrate": 115200, "read_rate_hz": 100.0}
        for key, value in defaults.items():
            self.declare_parameter(key, value, ParameterDescriptor(read_only=True))
        rate = self.get_parameter("read_rate_hz").value
        baud = self.get_parameter("baudrate").value
        if not math.isfinite(rate) or rate <= 0 or baud <= 0:
            raise ValueError("read_rate_hz and baudrate must be positive")
        self.transport = SerialTransport(port=self.get_parameter("port").value,
            baudrate=baud, read_timeout=0.0, write_timeout=0.05)
        self.buffer = bytearray()
        self.retry_at = 0.0
        self.connection_id = 0
        self.was_connected = False
        from rclpy.qos import QoSProfile, DurabilityPolicy
        self.link_pub = self.create_publisher(LinkState, "~/link_state",
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.outputs = {kind: (cls, self.create_publisher(cls, topic, 100)) for kind, cls, topic in (
            (0x85, WheelFeedback, "~/wheel_feedback"),
            (0x86, VoltageFeedback, "~/voltage_feedback"),
            (0x87, McuStatus, "~/mcu_status"))}
        self.create_timer(1.0 / rate, self.read_feedback)

    def read_feedback(self):
        if not self.transport.is_open():
            self.buffer.clear()
            self.update_link(False)
            if time.monotonic() < self.retry_at:
                return
            self.retry_at = time.monotonic() + 1.0
            if not self.transport.open():
                return
            self.update_link(True)
        for _ in range(8):
            chunk = self.transport.read(512)
            if not self.transport.is_open():
                self.buffer.clear()
                self.update_link(False)
                return
            self.buffer.extend(chunk)
            while True:
                decoded = try_parse_packet(self.buffer, self.protocol_error)
                if decoded is None:
                    break
                kind, fields = decoded
                cls, publisher = self.outputs[kind]
                message = cls(version=1, **fields)
                message.connection_id = self.connection_id
                message.received_at = self.get_clock().now().to_msg()
                publisher.publish(message)
            if len(chunk) < 512:
                break

    def update_link(self, connected):
        if connected == self.was_connected:
            return
        self.was_connected = connected
        if connected:
            self.connection_id += 1
        self.link_pub.publish(LinkState(changed_at=self.get_clock().now().to_msg(),
            connected=connected, connection_id=self.connection_id))

    def protocol_error(self, reason):
        self.get_logger().warning(reason, throttle_duration_sec=2.0)

    def destroy_node(self):
        self.transport.close()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = McuBridgeNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
