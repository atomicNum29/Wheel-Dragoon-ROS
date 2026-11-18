# Host-generated command in SI units. stamp is generation time, not an MCU ACK.
builtin_interfaces/Time stamp
# Bind queued commands to the observed MCU/host connection boundary.
uint64 connection_id
uint8 session
bool enable
bool estop
bool pivot
float64 linear_velocity
float64 steering_angle
float64 angular_velocity
