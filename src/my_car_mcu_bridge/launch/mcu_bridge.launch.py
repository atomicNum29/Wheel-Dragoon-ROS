import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    config = os.path.join(get_package_share_directory("my_car_mcu_bridge"), "config", "mcu_bridge.yaml")
    return LaunchDescription([
        Node(package="my_car_mcu_bridge", executable="mcu_bridge_node", name="mcu_bridge_node", parameters=[config], output="screen"),
        Node(package="my_car_mcu_bridge", executable="telemetry_aggregator", name="telemetry_aggregator", output="screen"),
    ])
