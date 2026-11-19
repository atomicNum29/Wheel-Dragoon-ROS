# Effective operating mode; healthy receiver failsafe can still report AUTO.
uint8 MODE_STOP=0
uint8 MODE_MANUAL=1
uint8 MODE_AUTO=2
uint8 MODE_POWERDOWN=3
uint8 MODE_PIVOT=4
uint8 MODE_FAILSAFE=5
uint8 STATE_ESTOP=3
uint16 FLAG_ESTOP_ACTIVE=32
uint16 FLAG_DRIVER_POWERDOWN=128
uint16 FLAG_DRIVER_STARTING=256

uint8 version
# Host connection generation; not an MCU boot identifier.
uint64 connection_id
builtin_interfaces/Time received_at
uint16 seq
uint8 state
uint8 mode
uint8 transition
# ESTOP_ACTIVE covers host estop and MCU control-signal-loss estop.
uint16 flags
uint16 system_error
uint8 validity
int16 requested_v_milli
int16 requested_theta_milli
int16 requested_w_milli
int16 applied_v_milli
int16 applied_theta_milli
int16 applied_w_milli
uint8 applied_mode
uint8 session
