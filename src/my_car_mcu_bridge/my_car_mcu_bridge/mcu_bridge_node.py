"""Typed MCU feedback and latest-command 0x03 transmission."""
import math
import time
import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor
from my_car_interfaces.msg import WheelFeedback, VoltageFeedback, McuStatus, LinkState, MotionCommand
from my_car_mcu_bridge.protocol import try_parse_packet, pack_motion_command
from my_car_mcu_bridge.serial_transport import SerialTransport

class McuBridgeNode(Node):
    def __init__(self):
        super().__init__("mcu_bridge_node")
        defaults = {"port": "/dev/ttyACM0", "baudrate": 115200, "read_rate_hz": 100.0,
                    "send_rate_hz": 50.0, "command_timeout_sec": 0.3}
        for key, value in defaults.items():
            self.declare_parameter(key, value, ParameterDescriptor(read_only=True))
        rate = self.get_parameter("read_rate_hz").value
        baud = self.get_parameter("baudrate").value
        if not math.isfinite(rate) or rate <= 0 or baud <= 0:
            raise ValueError("read_rate_hz and baudrate must be positive")
        self.send_rate = self.get_parameter("send_rate_hz").value
        self.command_timeout = self.get_parameter("command_timeout_sec").value
        if (not math.isfinite(self.send_rate) or self.send_rate <= 0
                or not math.isfinite(self.command_timeout) or not 0 < self.command_timeout < 0.5):
            raise ValueError("positive send_rate_hz and command_timeout_sec in (0, 0.5) required")
        self.command = None
        self.command_at = 0.0
        self.command_seq = 0
        self.mcu_status = None
        self.mcu_status_at = 0.0
        self.connected_at = 0.0
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
        self.create_subscription(MotionCommand, "~/command", self.accept_command, 1)
        self.create_timer(1.0 / self.send_rate, self.send_command)

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
                if kind == 0x87:
                    if (self.mcu_status is not None and
                            (message.session != self.mcu_status.session or message.mode != self.mcu_status.mode)):
                        self.command = None
                    self.mcu_status = message
                    self.mcu_status_at = time.monotonic()
                    if self.command is not None and self.command.enable and (
                            message.mode != McuStatus.MODE_AUTO or message.flags & (
                                McuStatus.FLAG_DRIVER_POWERDOWN | McuStatus.FLAG_DRIVER_STARTING)):
                        self.command = None
                publisher.publish(message)
            if len(chunk) < 512:
                break

    def update_link(self, connected):
        if connected == self.was_connected:
            return
        self.was_connected = connected
        self.command = None
        self.mcu_status = None
        self.mcu_status_at = 0.0
        if connected:
            self.connection_id += 1
            self.connected_at = time.monotonic()
        self.link_pub.publish(LinkState(changed_at=self.get_clock().now().to_msg(),
            connected=connected, connection_id=self.connection_id))

    def link_ready(self, now):
        # Require recently observed CONTROL feedback before attempting a command.
        return (self.transport.is_open() and self.mcu_status is not None
                and now - self.mcu_status_at <= self.command_timeout
                and now - self.connected_at > 0.55)

    def auto_ready(self, now):
        # The MCU retains effective AUTO during healthy receiver failsafe.
        # FAILSAFE and its POWERDOWN recovery phase never permit enabled output.
        return (self.link_ready(now) and self.mcu_status.mode == McuStatus.MODE_AUTO
                and not self.mcu_status.flags & (
                    McuStatus.FLAG_DRIVER_POWERDOWN | McuStatus.FLAG_DRIVER_STARTING))

    def accept_command(self, message):
        now = time.monotonic()
        try:
            values = (message.linear_velocity, message.steering_angle, message.angular_velocity)
            if not all(math.isfinite(v) for v in values):
                raise ValueError("non-finite command")
            if not (-2 <= values[0] <= 2 and -0.845 <= values[1] <= 0.845 and -5 <= values[2] <= 5):
                raise ValueError("motion command outside MCU limits")
            if (message.pivot and (values[0] != 0 or values[1] != 0)) or (not message.pivot and values[2] != 0):
                raise ValueError("unused command fields must be zero")
            age = (self.get_clock().now().nanoseconds -
                   (message.stamp.sec * 1000000000 + message.stamp.nanosec)) / 1e9
            if not 0 <= age <= self.command_timeout:
                raise ValueError("stale or future command stamp")
            if not message.enable and any(values):
                raise ValueError("disabled commands must have zero motion fields")
            if (not self.link_ready(now) or message.connection_id != self.connection_id
                    or message.session != self.mcu_status.session
                    or (message.enable and not self.auto_ready(now))):
                self.command = None
                return
            self.command = message
            self.command_at = now
        except ValueError as error:
            self.command = None
            self.protocol_error(str(error))

    def write_command(self, v=0, theta=0, w=0, *, enable=False, estop=False, pivot=False):
        packet = pack_motion_command(self.command_seq, v, theta, w,
            enable=enable, estop=estop, pivot=pivot)
        self.command_seq = (self.command_seq + 1) & 65535
        if not self.transport.write(packet):
            self.transport.close()
            self.buffer.clear()
            self.update_link(False)

    def send_command(self):
        now = time.monotonic()
        if not self.link_ready(now):
            self.command = None
            return
        message = self.command
        if message is None:
            return
        if message.enable and not self.auto_ready(now):
            self.command = None
            self.write_command(estop=message.estop)
            return
        age = (self.get_clock().now().nanoseconds -
               (message.stamp.sec * 1000000000 + message.stamp.nanosec)) / 1e9
        if now - self.command_at > self.command_timeout or not 0 <= age <= self.command_timeout:
            self.command = None
            # One disable on expiry; never replay the old target. Keep estop asserted.
            self.write_command(estop=message.estop)
            return
        self.write_command(round(message.linear_velocity * 1000),
            round(message.steering_angle * 1000), round(message.angular_velocity * 1000),
            enable=message.enable, estop=message.estop, pivot=message.pivot)

    def protocol_error(self, reason):
        self.get_logger().warning(reason, throttle_duration_sec=2.0)

    def destroy_node(self):
        # Never reopen a port during shutdown. MANUAL/PIVOT remain RC-owned.
        if self.command is not None and self.link_ready(time.monotonic()):
            self.write_command(estop=self.command.estop)
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
