uint8 version
# Host connection generation; not an MCU boot identifier.
uint64 connection_id
# received_at is host ROS arrival time, not MCU measurement time.
builtin_interfaces/Time received_at
uint16 seq
uint8 wheel_id
uint32 rx_timestamp_us
uint8 status
int16 rpm
int32 encoder_count
