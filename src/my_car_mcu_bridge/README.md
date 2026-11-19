# my_car_mcu_bridge

현재 코드는 Wheel-Dragoon의 split telemetry v1 수신·0x03 v1 명령 송신 브리지와 별도 집계 노드를 제공한다. 패키지 이름은 `my_car_mcu_bridge`, 송수신 실행 파일/노드 이름은 `mcu_bridge_node`다.

피드백을 수신하고 `/mcu_bridge_node/command`의 `MotionCommand`를 `0x03 v1`으로 인코딩·송신한다. `/cmd_vel` 변환, 보호 리셋, CAN 진단 요청은 구현하지 않는다. 구형 `0x81/0x82`와 legacy fallback은 지원하지 않는다.

## 실행과 설정

ROS 환경에서 워크스페이스 루트 기준:

```bash
colcon build --symlink-install --packages-up-to my_car_mcu_bridge
source install/local_setup.bash
ros2 launch my_car_mcu_bridge mcu_bridge.launch.py
```

launch는 `mcu_bridge_node`와 `telemetry_aggregator`를 함께 실행한다. 웹까지 빌드할 때는 웹 Python 환경을 준비한 뒤 [워크스페이스 안내](../../README.md)를 따른다. 이 명령들은 사용 절차이며 이번 문서 작업에서 실행한 검증 결과가 아니다.

[mcu_bridge.yaml](config/mcu_bridge.yaml)의 시작 전용 파라미터:

| 이름 | 기본값 | 의미 |
| --- | --- | --- |
| port | /dev/ttyACM0 | 시리얼 장치 |
| baudrate | 115200 | pyserial 연결 설정, 양수 |
| read_rate_hz | 100.0 | 읽기 타이머 Hz, 유한한 양수 |
| send_rate_hz | 50.0 | 최신 명령 송신 타이머 Hz, 유한한 양수 |
| command_timeout_sec | 0.3 | ROS 명령·상태 만료, 0 초과 0.5 미만 |

설정은 노드 재시작 시 적용한다. launch 인자는 별도로 선언하지 않는다. 포트를 일회성으로 바꾸려면 launch 대신 아래 두 노드를 각 터미널에서 실행한다.

```bash
ros2 run my_car_mcu_bridge mcu_bridge_node --ros-args -p port:=/dev/ttyACM1
```

```bash
ros2 run my_car_mcu_bridge telemetry_aggregator
```

집계 노드는 기본 절대 토픽 이름을 사용하므로 namespace를 바꾸려면 관련 구독·발행을 함께 remap해야 한다. 포트는 한 프로세스만 사용한다. 예전 설치 산출물은 자동 제거하지 않으며, 구형 노드를 중복 실행하지 않는다.

## USB 프레이밍과 디코딩

`AA 55`, length, type, payload, XOR 순서이며 전체 크기는 `length + 4`다. 다바이트 정수는 little-endian이다. length는 type부터 payload 끝까지의 크기다. XOR는 마지막 checksum을 포함한 전체 프레임에서 0이어야 한다.

| type | version | length / 전체 bytes | 현재 ROS 동작 |
| --- | --- | --- | --- |
| 0x85 | 1 | 16 / 20 | 휠 원시 피드백 발행 |
| 0x86 | 1 | 11 / 15 | 드라이버 전압 발행 |
| 0x87 | 1 | 25 / 29 | MCU 상태·지령 발행 |
| 0x84 | 미디코딩 | 59 / 63 | 길이·XOR 확인 후 전체 소비, 발행 안 함 |
| 0xA0 | 미디코딩 | 14 / 18 | 위와 동일 |
| 0xA1 | 미디코딩 | 52 / 56 | 위와 동일 |

파서는 누적 bytearray에서 프레임 일부를 보존하고 한 read의 여러 패킷을 순차 처리한다. 잘못된 type/길이·checksum은 한 바이트 이동하여 재동기화한다. 정상 프레임의 미지원 version은 전체 소비 후 경고하고 발행하지 않는다. wheel/driver ID와 mode(0..5)/transition(0..5) 범위를 검사한다. flags/state/예약 필드의 모든 의미를 검증하는 파서는 아니며, 허용된 프레임의 나머지 필드는 그대로 보존한다.

한 읽기 callback은 최대 512 bytes × 8회를 읽는다. 검증·디코딩한 피드백은 추가 동기화 대기 없이 즉시 발행한다. 기본 읽기 타이머 100Hz는 메시지 발행률 보장이 아니다. MCU는 유효 CAN 응답마다 0x85/86을 만들고 0x87은 목표 100Hz로 생성하므로 서로 다른 주기로 도착할 수 있다.

## 토픽과 QoS

아래 경로는 기본 노드 이름·namespace 기준이다. 타입의 패키지는 모두 `my_car_interfaces/msg`다.

| 발행 노드 | 토픽 | 타입 | QoS |
| --- | --- | --- | --- |
| mcu_bridge_node | /mcu_bridge_node/wheel_feedback | WheelFeedback | reliable, volatile, depth 100 |
| mcu_bridge_node | /mcu_bridge_node/voltage_feedback | VoltageFeedback | reliable, volatile, depth 100 |
| mcu_bridge_node | /mcu_bridge_node/mcu_status | McuStatus | reliable, volatile, depth 100 |
| mcu_bridge_node | /mcu_bridge_node/link_state | LinkState | reliable, transient-local, depth 1 |
| telemetry_aggregator | /telemetry | RobotTelemetry | reliable, volatile, depth 10 |

원시 토픽은 유효하게 디코딩된 중복 seq도 발행한다. 헤더·length·type·checksum은 검증/분배에 사용하며 메시지에 복사하지 않는다. 세 피드백의 정보 필드와 version은 보존하고 host connection_id·received_at을 추가한다. [필드 정의·단위](../my_car_interfaces/README.md)를 참고한다. ROS 발행은 무손실 기록이나 host 저장 완료를 보증하지 않는다.

## 연결 경계

포트를 열 수 없으면 최소 1초 간격으로 다시 시도한다. 연결이 닫히거나 read에서 단절을 감지하면 프레임 버퍼를 비운다. 포트가 열리면 host `connection_id`를 증가시키고 LinkState를 발행한다. 이 값은 노드 재시작 시 0부터 시작하며 MCU boot ID가 아니다.

LinkState는 연결 상태가 바뀔 때만 발행한다. 시작 직후 계속 연결에 실패하면 초기 false 메시지를 별도 발행하지 않는다. 정상 종료는 포트를 닫으며 마지막 false 메시지를 별도 발행하지 않는다. 포트 open 상태는 MCU 응답 정상이나 물리적 안전 상태의 증명이 아니다.

별도 모드 전환 요청 인터페이스는 없다. 0x03 자체는 MCU를 CONTROL로 복귀시키는 효과가 있지만, 브리지는 최근 0x87이 없으면 명령을 송신하지 않는다. 따라서 MCU가 이미 BRIDGE/RESETTING이고 피드백이 없는 상태에서 이 노드를 시작해도 자동 복귀하지 않는다. 진단 세션과 일반 제어 송신은 동시에 사용하지 않는다. CONTROL에서는 RC 수동 주행 중에도 피드백 수집이 가능하다.

## 제어 명령 0x03 v1

기본 구독 토픽은 `/mcu_bridge_node/command`, 타입은 `my_car_interfaces/msg/MotionCommand`, reliable / volatile depth 1이다. 단일 명령 발행 주체를 사용한다. 여러 ROS publisher 사이의 우선권 조정은 구현하지 않는다.

ROS 입력은 SI 단위 선속도·중앙 조향각·PIVOT 각속도다. 각 필드를 1000배하고 반올림하여 아래 패킷으로 인코딩한다.

| offset | 타입 | 값 |
| --- | --- | --- |
| 0–3 | 4 bytes | AA 55 0B 03 |
| 4 | u8 | version=1 |
| 5 | u16 | 송신마다 증가하는 seq, 65535→0 |
| 7 | u8 | bit0 enable / bit1 estop / bit2 PIVOT, 예약 0 |
| 8 | i16 | 선속도 milli-m/s, ±2000 |
| 10 | i16 | 중앙 조향각 milli-rad, ±845 |
| 12 | i16 | PIVOT 각속도 milli-rad/s, ±5000 |
| 14 | u8 | 앞선 14 bytes XOR |

일반 모드에서는 ω=0, PIVOT에서는 v=θ=0이어야 한다. NaN/Infinity·범위 초과·미사용 필드 비영을 거부한다. 조향 상한은 현재 MCU 기하에 맞춘 값이다.

ROS stamp는 생성 시각이며 브리지와 같은 ROS 시간 기준을 사용해야 한다. 수신과 송신 모두 stamp age가 0..command_timeout_sec인지 확인한다. connection_id/session은 현재 피드백 경계와 일치해야 한다. stamp·connection_id·session은 host 검증용이며 wire에는 포함하지 않는다.

포트 연결 후 0.55초 대기하고, 최신 0x87이 있는 CONTROL 상태에서 0·disable 명령을 받는다. enable=true 명령은 추가로 MCU 유효 운용 모드가 AUTO이며 POWERDOWN/드라이버 시작 대기가 아닐 때만 허용한다. disable 명령의 motion 필드는 모두 0이어야 한다. 이 대기는 RC 모드 전환마다 재시작하지 않는다. 호스트 재시작으로 초기화된 seq에 대해 MCU의 이전 명령 timeout을 기다리기 위한 것이다. seq는 포트 재연결만으로 초기화하지 않는다. MCU ACK/수락 seq echo는 없다.

최신 목표 하나만 유지하고 같은 목표도 새 seq로 송신한다. 명령 만료 시 enable=0을 한 번 시도하고 캐시를 비운다. 활성 estop은 만료 시 disable에도 유지한다. 포트 단절·RC 모드 또는 CONTROL session 변경·상태 만료에서는 목표를 폐기하며 재연결 후 재생하지 않는다. 상태가 없어 송신을 멈춘 경우 MCU 자체 500ms timeout이 남은 정지 경로다.

정상 0속도(enable=1)는 MCU 모션 스케줄러 감속, enable=0은 TQ-OFF 경로다. estop=1은 AUTO에서 즉시 TQ-OFF 시도와 비상 조향 자세 요청이다. MANUAL/PIVOT은 RC 권한이며 host estop이 전역 정지가 아니다. 정상 종료는 아직 유효한 활성 명령과 CONTROL 피드백이 있는 경우 enable=0을 시도하고 포트를 닫는다. 시리얼 write 성공은 차량 정지 확인이 아니다.

## 최신값 집계

`telemetry_aggregator`는 개별 토픽을 구독하고 고정 0.05초 타이머로 `/telemetry`를 발행한다. 집계 전용 설정 파라미터는 없다.

- 현재 연결 번호와 일치하고 첫 MCU 상태를 받은 이후의 휠/전압을 받는다.
- 스트림별 `delta=(new_seq-old_seq)&65535`가 1..32767일 때 새 샘플로 채택한다. 중복·역순은 집계에서 제외한다.
- LinkState 수신, MCU session 변경, 마지막 채택 상태로부터 1초 초과 공백에서 전체 캐시를 비운다. 상태 공백은 재부팅 증명이 아닌 로컬 집계 경계다.
- 미수신 항목은 기본 메시지를 넣되 present=false, age=-1로 표시한다. present=false일 때 기본 0을 측정값으로 해석하지 않는다.
- age는 집계 노드가 callback에서 채택한 후 monotonic 경과시간이다. MCU 측정 age나 USB 전송 지연을 포함한 전체 지연이 아니다.
- 휠/전압만 오래되어도 상태가 계속 들어오면 해당 샘플을 삭제하지 않고 age를 증가시킨다. 최종 소비자가 MCU validity와 age를 함께 평가한다.

휠/전압에는 MCU session이 없고 서로 다른 토픽은 전달 순서가 일치하지 않을 수 있다. 경계 부근의 샘플 소속을 완전히 복원하지 못한다. 집계는 동시 측정이나 보간이 아니다. 타임스탬프 확장·시간 동기화·엔코더 차분·오도메트리 적분·누락 횟수 집계는 구현하지 않는다.

## 상태와 지령 해석

state, 유효 운용 mode, transition은 서로 다른 정보다. DRIVING 단계도 실제 이동 확인이 아니며, motor_enabled와 drive gate도 드라이버 적용 ACK가 아니다. 요청 지령은 선택된 입력 목표, 적용 지령은 스케줄러의 생성 지령이다. 조향 실측값은 수신하지 않는다.

0x87에는 MCU timestamp나 uptime이 없다. ROS received_at을 MCU 생성 시각이라고 해석하지 않는다. 휠/전압의 rx_timestamp_us는 CAN ISR 수신 시각이며 uint32로 약 71.6분마다 순환한다. 순번과 session도 순환하므로 모든 재시작을 판별할 수 없다.

## Firmware error reporting rules

MCU 규격의 의미를 설명하며 ROS는 오류 카운터를 재현하거나 비트를 지우지 않는다.

| error bit | 의미 |
| --- | --- |
| 0 | USB checksum 오류 |
| 1 | command timeout 보고 |
| 2 | CAN 안전 송신 또는 전압 조회 실패 |
| 3 | host estop 또는 제어 신호 상실 비상 정지 보고 |
| 4 | 저전압 |
| 5 | framing / 지원하지 않는 요청 |
| 6 | 명령 범위 또는 운동 모드 필드 오류 |
| 7 | 예약, watchdog 감지 소스 없음 |
| 8 | 드라이버 원시 상태 비영 |
| 9 | 드라이버 응답 창 누락 |
| 10 | 전압 stale |
| 11 | CAN RX overrun 관측 |
| 12 | USB 송신 데이터 누락 |
| 13 | USB write 반환 길이 불일치 |
| 14–15 | 예약 |

일반 오류는 감지 시 잔여 보고 10회로 갱신한다. 0x87 전체 송신 완료 후 해당 스냅샷의 CONTROL 세션·오류 revision·CAN overrun 수가 현재와 같을 때 카운터를 감소시킨다. 휠·전압·진단 송신은 차감 조건이 아니다. bit12/13은 별도 래치이며 같은 세션에서 해당 오류를 담은 상태 프레임 전체 write가 끝나고 이후 재감지가 없을 때 해제한다. 아직 보고하지 못한 USB 오류는 세션 초기화만으로 지워지지 않는다.

과거 보고 비트와 현재 활성 estop/timeout을 구분하며 최종 MCU state를 함께 확인한다. USB bit12/13 보고 비트 자체는 직접 구동 차단 조건이 아니다. 다만 실제 송신 실패·폐기·스킵 이벤트는 MCU AUTO 구간의 USB 이상 집계에 포함되며 수신기 failsafe와 겹치면 제어 신호 상실 비상 정지로 이어질 수 있다. 드라이버 fault·저전압 등 차단 조건은 MCU가 판단하며 ROS 화면은 관측값을 표시한다. host ACK나 로그 저장 확인 규격은 없다.

펌웨어 규격 근거: 형제 저장소 [USB 프로토콜](../../../Wheel-Dragoon/docs/usb-protocol.ko.md), [ROS USB 연동](../../../Wheel-Dragoon/docs/ros-usb-integration.ko.md). 형제 저장소가 함께 배치되어 있어야 이 링크가 열린다.

## 수신기 failsafe와 제어 신호 상실 복구

Wheel-Dragoon `8bf301e` 기준이다. `0x03`은 15바이트 v1, `0x87`은 29바이트 v1로 기존과 같다. 새 FAILSAFE 운용 모드 5를 허용하며 모든 피드백 필드를 기존 타입으로 발행한다. 메시지 상수가 추가되므로 인터페이스와 소비 노드를 함께 다시 빌드한다.

수신기 모드 채널의 중앙값은 POWERDOWN=1000, STOP=1200, MANUAL=1400, PIVOT=1600, AUTO=1800, 수신기 failsafe=2000µs다. 펌웨어 구간은 1100 미만 POWERDOWN, 1100..1300 미만 STOP, 1300..1500 미만 MANUAL, 1500..1700 미만 PIVOT, 1700..1900 미만 AUTO이며, 원시 유효 펄스 1900µs 이상은 즉시 failsafe로 판정한다. 수신기가 이 값을 출력하도록 구성해야 한다. 펄스 자체의 수신 중단 타이머는 추가되지 않았다.

수신기 failsafe 때 MCU는 다음 조건을 만족하면 유효 mode=AUTO와 기존 명령을 유지한다: 이미 AUTO, 해당 AUTO 구간에서 USB 명령 수락 및 정상 송신 이력 존재, CONTROL 상태, 드라이버 전원 차단/시작 대기·host estop·driver fault·저전압 없음, USB 이상 한계 미도달. 정상 USB AUTO 유지 중에는 ROS의 기존 AUTO 송신 경로를 그대로 사용하며 연결이나 명령을 초기화하지 않는다.

그 밖에는 MCU가 제어 신호 상실 비상 정지를 래치하고 릴레이를 차단하며 비상 조향을 요청한다. mode=FAILSAFE(5), state=ESTOP(3), flags bit5/7=1이다. STOP·MANUAL·AUTO 선택이나 USB 명령만으로 래치를 풀 수 없다. 복구는 실제 RC POWERDOWN 진입 후 STOP 전환으로 수행한다. 복구 단계의 POWERDOWN은 mode=3이지만 state=3, bit5/7=1로 보고되므로 host estop과 구분한다. MCU는 복구 후 1000ms 드라이버 시작 대기와 중립 조향 복귀를 처리한다. ROS는 복구용 가짜 estop 해제·보호 리셋·전원 명령을 보내지 않는다.

MCU의 USB 건강 상태 정책은 AUTO 진입 시 초기화되며 RX/TX 연속 이상을 따로 센다. 수신 또는 송신 연속 5회 또는 양방향 누적 30회에 도달하면 해당 AUTO 구간에서 한계 도달을 유지한다. seq 건너뜀도 수신 이상으로 집계하므로 브리지는 최신 목표 재송신마다 순차 u16 seq를 사용한다. 반대 방향 정상 통신은 다른 방향의 연속 횟수를 지우지 않는다.

마지막 수락 명령 후 500ms 초과 시 기존 timeout 정지가 먼저 적용된다. 이후 60ms마다 RX 이상을 집계하므로 timeout이 300ms 지속되면 연속 5회, 즉 마지막 수락 후 총 800ms에서 한계에 도달한다. RC가 정상일 때 이 이상 집계만으로 릴레이를 차단하지는 않는다. 구체적 집계·구동 판정은 MCU가 수행하며 ROS는 보고 비트로 연속/누적 횟수를 역산하지 않는다.

## 검증 범위

현재 문서는 소스와 메시지 정의를 정적으로 대조한 설명이다. 이 문서 정리에서 빌드·테스트·실물 통신은 수행하지 않았다. 과거 테스트는 [보관 안내](../../agent/README.md)를 따른다.
