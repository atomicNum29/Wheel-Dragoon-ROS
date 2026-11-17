from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from pathlib import Path
import os


def generate_launch_description():

    rpi_cameras = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(Path(__file__).parent / "rpi_cameras.launch.py")
    )

    lidar_launch = os.path.join(
        get_package_share_directory("ydlidar_ros2_driver"),
        "launch",
        "ydlidar_launch.py",
    )
    lidar = IncludeLaunchDescription(PythonLaunchDescriptionSource(lidar_launch))

    t265_launch = os.path.join(
        get_package_share_directory("realsense2_camera"),
        "launch",
        "rs_launch.py",
    )
    t265 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(t265_launch),
        launch_arguments={
            "device_type": "t265",
            "enable_accel": "true",
            "enable_gyro": "true",
        }.items(),
    )

    mcu_bridge_launch = os.path.join(
        get_package_share_directory("my_car_mcu_bridge"),
        "launch",
        "mcu_bridge.launch.py",
    )
    mcu_bridge = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(mcu_bridge_launch)
    )

    return LaunchDescription([rpi_cameras, lidar, t265, mcu_bridge])
