# my_car_interfaces

MCU 피드백과 최신값 집계용 ROS 2 전용 메시지 패키지다. `ament_cmake`와 `rosidl_default_generators`로 생성하며 `builtin_interfaces`에 의존한다. JSON 문자열 또는 USB byte 배열이 아닌 ROS typed message다.

메시지 정의는 [msg/](msg/)에 있다. 아래 필드 순서·타입은 현재 `.msg` 정의와 같다. ROS 타입의 bytes와 MCU wire packet 크기는 서로 다르다.

## 공통 의미

- version: 디코딩한 피드백 규격 버전, 현재 1만 발행한다.
- connection_id: host 포트 연결 세대. 연결 성공마다 증가하고 수신 노드 재시작 때 초기화된다. MCU boot ID가 아니다.
- received_at: 수신 노드의 ROS clock으로 기록한 디코딩/발행 직전 시각이다. 장치 측정 시각이 아니다.
- seq: 휠별/드라이버별/상태별 독립 u16 생성 순번. 65535 다음 0이다.
- rx_timestamp_us: MCU CAN ISR의 uint32 micros 시각이다. uint32 순환을 그대로 보존한다.
- ROS Time: int32 sec + uint32 nanosec. MCU 시각과의 동기화는 제공하지 않는다.

## WheelFeedback

| 타입 | 필드 | 의미 |
| --- | --- | --- |
| `uint8` | `version` | 피드백 규격 버전 |
| `uint64` | `connection_id` | host 연결 세대 |
| `builtin_interfaces/Time` | `received_at` | host ROS 수신 처리 시각 |
| `uint16` | `seq` | 스트림별 MCU 생성 순번 |
| `uint8` | `wheel_id` | 0 LF / 1 RF / 2 LR / 3 RR |
| `uint32` | `rx_timestamp_us` | MCU CAN ISR 수신 시각, µs |
| `uint8` | `status` | 원시 드라이버 상태 바이트 |
| `int16` | `rpm` | 원시 signed RPM |
| `int32` | `encoder_count` | 원시 signed 엔코더 누적 카운트 |

## VoltageFeedback

| 타입 | 필드 | 의미 |
| --- | --- | --- |
| `uint8` | `version` | 피드백 규격 버전 |
| `uint64` | `connection_id` | host 연결 세대 |
| `builtin_interfaces/Time` | `received_at` | host ROS 수신 처리 시각 |
| `uint16` | `seq` | 스트림별 MCU 생성 순번 |
| `uint8` | `driver_id` | 0 A / 1 B (CAN ID 자체가 아님) |
| `uint32` | `rx_timestamp_us` | MCU CAN ISR 수신 시각, µs |
| `uint16` | `voltage_mv` | 전압 mV, MCU 원시 분해능은 100mV |

## McuStatus

| 타입 | 필드 | 의미 |
| --- | --- | --- |
| `uint8` | `version` | 피드백 규격 버전 |
| `uint64` | `connection_id` | host 연결 세대 |
| `builtin_interfaces/Time` | `received_at` | host ROS 수신 처리 시각 |
| `uint16` | `seq` | 스트림별 MCU 생성 순번 |
| `uint8` | `state` | MCU 구동/오류 상태 |
| `uint8` | `mode` | RC 운전 모드 |
| `uint8` | `transition` | 모션 스케줄러 단계 |
| `uint16` | `flags` | 상태 bit mask |
| `uint16` | `system_error` | 시스템 오류 bit mask |
| `uint8` | `validity` | bit0–3 휠, bit4–5 전압 A/B |
| `int16` | `requested_v_milli` | 입력 목표; 0.001 m/s |
| `int16` | `requested_theta_milli` | 입력 목표; 0.001 rad |
| `int16` | `requested_w_milli` | 입력 목표; 0.001 rad/s |
| `int16` | `applied_v_milli` | 스케줄러 적용 지령; 0.001 m/s |
| `int16` | `applied_theta_milli` | 스케줄러 적용 지령; 0.001 rad |
| `int16` | `applied_w_milli` | 스케줄러 적용 지령; 0.001 rad/s |
| `uint8` | `applied_mode` | 1 일반 v·θ / 4 PIVOT ω / 255 무효 |
| `uint8` | `session` | CONTROL 세션 번호, uint8 순환 |

## LinkState

| 타입 | 필드 | 의미 |
| --- | --- | --- |
| `builtin_interfaces/Time` | `changed_at` | 연결 상태 변경을 기록한 host ROS 시각 |
| `bool` | `connected` | 포트 open 여부 |
| `uint64` | `connection_id` | host 연결 세대 |

## RobotTelemetry

| 타입 | 필드 | 의미 |
| --- | --- | --- |
| `builtin_interfaces/Time` | `published_at` | 집계 메시지 생성 시각, host ROS clock |
| `bool` | `status_present` | MCU 상태 캐시 존재 여부 |
| `float64` | `status_age_sec` | 집계가 상태를 채택한 후 monotonic 경과 초, 없으면 -1 |
| `McuStatus` | `status` | 최신 MCU 상태 메시지; status_present=true일 때 해석 |
| `WheelFeedback[4]` | `wheels` | LF/RF/LR/RR 순서의 최신 피드백 |
| `bool[4]` | `wheel_present` | 휠 캐시 존재 여부, MCU validity와 별개 |
| `float64[4]` | `wheel_age_sec` | 휠 채택 후 경과 초, 없으면 -1 |
| `VoltageFeedback[2]` | `drivers` | A/B 순서의 최신 전압 |
| `bool[2]` | `driver_present` | 전압 캐시 존재 여부 |
| `float64[2]` | `driver_age_sec` | 전압 채택 후 경과 초, 없으면 -1 |

## MCU 상태 열거값과 flags

state: 0 DISABLED, 1 ENABLED, 2 TIMEOUT_STOP, 3 ESTOP, 4 FAULT, 5 BOOTING, 6 예약, 7 DRIVER_POWERDOWN.

RC mode: 0 STOP, 1 MANUAL, 2 AUTO, 3 POWERDOWN, 4 PIVOT.

transition: 0 STARTUP, 1 DRIVING, 2 BRAKING, 3 STEERING, 4 SETTLING, 5 EMERGENCY_STOP.

| flags bit | 의미 |
| --- | --- |
| 0 | motor_enabled |
| 1 | motion ready |
| 2 | motion feasible |
| 3 | RPM 크기 상한 적용, 모든 변화율 제한의 요약은 아님 |
| 4 | 요청 목표 유효 |
| 5 | 활성 host estop |
| 6 | 활성 host command timeout |
| 7 | driver powerdown |
| 8 | driver starting |
| 9 | CAN 구동 허용 gate |
| 10 | 조향 보정 유효 |
| 11 | 적용 지령 및 적용 모드 유효 |
| 12 | 요청 운동 모드 PIVOT; bit4 유효일 때 해석 |
| 13–15 | 예약 |

일반 요청은 v·θ, PIVOT 요청은 ω를 사용한다. θ는 가상 전륜 중앙 조향각이며 좌우 실측 조향각이 아니다. 적용 모드는 RC mode와 다를 수 있다. STEERING/SETTLING/EMERGENCY_STOP 등 표현 불가 자세에서 적용 모드=255, bit11=0, 적용값=0이 올 수 있으므로 무효 0을 실제 정지·직진으로 해석하지 않는다.

RobotTelemetry는 최신값 집합이다. present=false인 항목의 기본값은 측정값이 아니며, present=true여도 MCU validity와 age를 함께 확인해야 한다. 휠/전압에는 CONTROL session이 없고 상태에는 MCU timestamp가 없다. 동시 측정, boot 식별, 시각 동기화, 조향 추종을 보증하지 않는다. `/odom`으로 직접 사용할 수 있는 메시지가 아니다.

[토픽·집계·오류 규칙](../my_car_mcu_bridge/README.md) · [웹 표시 규칙](../my_car_web_monitor/README.md)
