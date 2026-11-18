cmake_minimum_required(VERSION 3.8)
project(my_car_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/MotionCommand.msg" "msg/LinkState.msg" "msg/WheelFeedback.msg" "msg/VoltageFeedback.msg"
  "msg/McuStatus.msg" "msg/RobotTelemetry.msg"
  DEPENDENCIES builtin_interfaces)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
