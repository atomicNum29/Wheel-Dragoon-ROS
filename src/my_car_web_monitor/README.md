# my_car_web_monitor

`web_monitor_node`는 피드백·LiDAR·영상 조회와 RC AUTO에서의 웹 수동 제어를 제공한다. `/cmd_vel` 대신 전용 `MotionCommand`로 v·θ/PIVOT 목표를 발행한다.

## 구성과 실행

하나의 프로세스에서 ROS `MultiThreadedExecutor`를 별도 스레드로 실행하고 FastAPI/Uvicorn 및 WebRTC를 함께 사용한다. ROS 내부는 전용 메시지이며, 브라우저 상태 전달 경계에서만 JSON으로 변환한다.

워크스페이스 루트에서 ROS 기본 환경을 불러온 뒤 웹 의존성을 준비한다. Picamera2는 시스템 카메라 스택에서 별도 제공해야 한다.

```bash
cd src/my_car_web_monitor
uv venv --python /usr/bin/python3 --system-site-packages
source .venv/bin/activate
uv sync --active
cd ../..
python -m colcon build --symlink-install --packages-up-to my_car_web_monitor my_car_mcu_bridge
source install/local_setup.bash
```

각각 별도 터미널에서 같은 ROS/가상환경을 활성화해 실행한다.

```bash
ros2 launch my_car_mcu_bridge mcu_bridge.launch.py
```

```bash
CAMERA_SOURCE=synthetic ros2 run my_car_web_monitor web_monitor_node
```

`http://localhost:8443` 또는 `http://<장비 IP>:8443`에 접속한다. 포트 번호와 무관하게 현재 서버는 HTTP이며 TLS를 설정하지 않는다. 합성 영상에서도 ROS와 생성된 `my_car_interfaces`가 필요하다. 브리지가 없으면 차량 정보는 수신 대기로 표시한다.

## ROS 입출력

| 방향 | 기본 토픽 | 타입 / 동작 |
| --- | --- | --- |
| 발행 | `/mcu_bridge_node/command` | `my_car_interfaces/msg/MotionCommand`, reliable / volatile depth 1, 제어 세션 중 20Hz |
| 구독 | `/telemetry` | `my_car_interfaces/msg/RobotTelemetry`, reliable / volatile depth 10 |
| 구독 | `/scan` | `sensor_msgs/msg/LaserScan`, best-effort / volatile depth 1 |
| 구독 | `CAMERA_STREAMS`의 ROS 이미지 토픽 | Image 또는 CompressedImage, 시청 중 구독 |

웹 노드는 시리얼 포트를 열지 않는다. `/telemetry`는 별도 `telemetry_aggregator`가 20Hz로 발행하며, 메시지 정의·집계 규칙은 [인터페이스](../my_car_interfaces/README.md)와 [브리지](../my_car_mcu_bridge/README.md)를 따른다. 오도메트리·실측 조향 JointState는 발행하지 않는다.

## 상태 변환과 freshness

`control.py`는 `RobotTelemetry`를 dict로 변환하고 `schema="split_v1"`로 표시한다. 상태에 `status_present/status_age_sec`, 휠·전압에 `present/age_sec/valid`를 붙여 웹 JSON을 만든다. MCU wire version은 1이다. JavaScript 내부의 `v2` 분기명은 재사용된 표시 코드의 이름이며 `0x82 v2` 지원을 뜻하지 않는다.

웹 JSON에서 `requested_*_milli`, `applied_*_milli`, flags, errors, session 및 개별 피드백의 seq·MCU RX 시각·host 수신 시각을 보존한다. 브라우저의 수신 원문은 이 변환된 JSON이며 USB 원시 바이트가 아니다. 집계 메시지의 `published_at` 자체는 현재 웹 JSON으로 전달하지 않는다.

표시 유효성은 다음을 함께 사용한다.

- MCU 상태: `status_present`, 집계 status age, 웹 수신 경과시간을 확인한다. 표시 한계는 1초다.
- 휠: `present`, 해당 validity bit, 집계 age와 웹 경과시간을 확인하며 한계는 1초다.
- 전압: 같은 조건에서 한계는 3초다. MCU 상태 자체가 오래되면 전압도 현재값으로 표시하지 않는다.
- 서버 연결과 숫자 필드의 타입·범위도 확인한다. 이 기준은 MCU CAN 응답 창 3ms와 다른 host 표시 정책이다.

`motor_status_age_sec`는 웹이 집계 메시지를 받은 후 경과시간이다. MCU 상태·각 샘플의 나이와 별개이며, 20Hz 집계가 계속 들어온다는 것만으로 MCU가 정상이라고 판단하지 않는다.

`/ws/status`는 관찰자별 256개 큐를 사용한다. 큐가 차면 오래된 항목을 제거하며 `stream_dropped_count`로 표시한다. `motor_status_received_count`는 웹 프로세스의 ROS 집계 메시지 수이지 MCU 패킷 수가 아니다. 서버는 새 상태가 없으면 1초마다 heartbeat를 보내고, 브라우저는 이를 새 측정으로 처리하지 않는다. 브라우저는 연결 종료 후 재접속하며, 누락된 과거 기록은 재생하지 않는다.

## UI

상단 제어 연결 버튼 옆에는 미연결/연결 중/연결됨·대기/연결됨·제어/연결됨·정지 확인/비상정지만 표시하고 상세 사유는 제어 영역에 표시한다. 조이스틱은 제어 영역 우측에 배치하며 일반 모드는 280px 높이, PIVOT은 96px 높이다. 좁은 화면에서는 아래로 배치한다.

상단에는 상태 수신 여부와 유효 운용 모드·모션 단계·구동 허용·조향 보정 상태를 한 줄로 표시한다. 전압 A/B와 목표·적용 지령을 가로로 배치한다. 목표/적용은 각각 선속도 m/s, 중앙 조향각 rad, PIVOT 각속도 rad/s를 표시한다.

목표는 flags bit4, 적용값은 bit11이 유효할 때만 표시한다. 목표 운동 모드는 bit12, 적용 운동 모드는 `applied_mode`로 판별한다. 일반 v·θ와 PIVOT ω에서 사용하지 않는 항목 또는 무효값은 `—`로 표시한다. `—`를 0으로 해석하지 않는다. 적용값은 실측값이 아니며, 구동 gate가 1이어도 실제 이동이나 CAN 적용 ACK가 아니다.

차량 상세는 기본 펼침이다. LF/RF와 LR/RR을 물리 배치대로 표시하고 RPM, 엔코더 카운트, 추정 회전수·거리, 수신 경과시간·seq·오류를 보여 준다. 회전수는 `encoder_count / 16384`, 거리는 회전수 × `π × 0.13m`로 계산한다. 이는 현재 UI의 고정 환산 가정이며 장비별 보정이나 오도메트리 적분이 아니다. 부호를 유지한 엔코더 원점 기준 값이다.

시스템 오류는 MCU state를 임의로 재계산하지 않고 수신 비트를 표시한다. bit12/13도 USB 송신 진단으로 표시한다. [오류 규칙](../my_car_mcu_bridge/README.md#firmware-error-reporting-rules)을 참고한다. 시스템 전체 비트와 원문 JSON은 접어서 볼 수 있다. 좁은 화면에서는 줄바꿈 또는 지령 표 가로 스크롤을 사용한다.

## 환경변수

설정은 시작 시 `config.py`에서 읽으며 변경 후 프로세스를 재시작한다.

| 환경변수 | 기본값 | 의미 |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8443` | HTTP 서버 |
| `MOTOR_STATUS_TOPIC` | `/telemetry` | RobotTelemetry 구독 토픽 |
| `CAMERA_SOURCE` | `picamera2` | 기본 단일 소스: picamera2 또는 synthetic |
| `CAMERA_STREAMS` | 빈 문자열 | `id:type[:device]`를 쉼표로 나열 |
| `CAMERA_WIDTH` / `CAMERA_HEIGHT` | `1280` / `720` | 직접 카메라·합성 영상 해상도 |
| `CAMERA_FPS` | `15` | 영상 출력 FPS |
| `WEBRTC_PACKET_MAX` | `1100` | WebRTC 인코더 RTP payload 크기 설정 |
| `LOG_LEVEL` | `info` | 로그 수준 |

현재 제어에는 `MCU_COMMAND_TOPIC=/mcu_bridge_node/command`, `CONTROL_RAMP_SECONDS=1.0`, `CONTROL_WATCHDOG_TIMEOUT=0.3`을 사용한다. 마우스 복귀 시간은 `CONTROL_MOUSE_RETURN_SECONDS=2.0`이다. 두 시간은 유한한 양수, watchdog은 0 초과 0.5 미만이어야 한다. 이전 Twist UI의 속도 설정은 코드에 남아 있지만 새 조작부에는 사용하지 않는다. `CMD_VEL_TOPIC=/cmd_vel`, `CONTROL_LINEAR_SPEED=2.0`, `CONTROL_ANGULAR_SPEED=3.0`, 각 축 MIN=0.0, DEFAULT=0.2/0.3, `CONTROL_WATCHDOG_TIMEOUT=0.3`이 기본값이다. 속도 설정은 여전히 시작 시 유한한 `0 ≤ min ≤ default ≤ max` 검사를 수행한다.

## HTTP / WebSocket

| 경로 | 현재 동작 |
| --- | --- |
| `GET /` / `/static/*` | 브라우저 UI·정적 파일 |
| `GET /health` | 웹 서버 응답, MCU 연결 보장은 아님 |
| `GET /time` | 서버 monotonic 시각, 영상 지연 추정용 |
| `GET /streams` | 영상 소스 목록 |
| `POST /offer` | stream_id/sdp/type로 WebRTC 협상 |
| `GET /control/config` | MCU 최대값과 입력 ramp 시간 조회 |
| `GET /control/status` | 최신 웹 상태 JSON 조회 |
| `/ws/status` | 읽기 전용 상태 스트림 |
| `/ws/scan` | 읽기 전용 LiDAR 바이너리 스트림 |
| `/ws/control` | 단일 제어 세션, 입력/heartbeat 수신과 목표 상태 응답 |

## 카메라 소스

`CAMERA_STREAMS`의 유효한 목록이 있으면 `CAMERA_SOURCE` 대신 사용한다. id는 유일해야 하며 ROS 소스는 토픽을 반드시 지정한다.

```bash
CAMERA_STREAMS=front:ros_image:/front_camera/image_raw,rear:ros_image:/rear_camera/image_raw \
  ros2 run my_car_web_monitor web_monitor_node
```

| type | device | 동작 |
| --- | --- | --- |
| picamera2 | 카메라 인덱스, 기본 0 | 시스템 Picamera2 사용 |
| synthetic | 생략 가능 | 합성 영상 |
| ros_image | 토픽 | sensor_msgs/msg/Image |
| ros_compressed | 토픽 | sensor_msgs/msg/CompressedImage |

ROS 영상은 mono8/8UC1/rgb8/bgr8/rgba8/bgra8와 JPEG/PNG 압축을 지원한다. 원본 해상도를 유지하며 depth 등 미지원 형식은 건너뛴다. best-effort / volatile depth 1로 최신 이미지 하나만 유지하고 출력 FPS로 샘플링한다. 첫 시청자가 구독을 시작하며 마지막 시청자가 나가면 해제한다. 첫 정상 이미지 전에는 대기하고, 발행이 중단되면 마지막 이미지를 반복하므로 정지 화면만으로 센서 freshness를 판단할 수 없다. 동일 카메라의 Picamera2 직접 접근과 ROS 드라이버 접근을 중복 실행하지 않는다.

## LiDAR

`/scan`의 유한한 양수이며 센서 범위 내인 거리 중 최대 7m까지 표시한다. 인덱스와 각도를 보존하고 거리는 mm로 양자화한다. TF나 설치 offset은 적용하지 않는다. 최신 스캔을 최대 10Hz로 전달하고 중간 스캔은 큐에 쌓지 않는다.

`/ws/scan`은 little-endian 32바이트 헤더 `<4sIfffdf`(LDR1, 원본 ray 수, angle_min, angle_increment, 반경 7m, ROS stamp 초, 서버 수신 age 초)와 `<IH`(원본 index, 거리 mm) 레코드를 사용한다. 브라우저는 1초 이상 오래된 스캔을 지우며 연결 종료 시에도 지운다.

## 구현 한계와 검증 상태

최신 프로토콜·UI에 대한 빌드·테스트·실물 검증은 이번 문서 정리에서 수행하지 않았다. `test/`에는 이전 JSON·제어·UI 전제의 테스트가 남아 있으므로 현행 규격 통과 근거가 아니다.

종료 시 활성 웹 출력이 있으면 enable=0을 발행하고 영상 소스를 정리한다. 제어 연결을 열지 않은 조회 전용 실행에서는 명령을 발행하지 않는다.

## 웹 조작

제어 연결은 RC 모드·MCU 피드백 유무와 무관하게 열 수 있으며, 연결 자체와 실제 구동 권한을 분리한다. 세션은 자동 재접속하지 않지만 일반 RC 모드 변경으로 끊지는 않는다. 피드백이 없거나 AUTO가 아니거나 드라이버 시작 대기/POWERDOWN이면 0·disable을 20Hz 발행한다. 최신 피드백에서 AUTO를 확인하면 현재 유효한 웹 입력과 enable을 발행한다. 비상정지는 이 조건보다 우선한다.

대기 중에도 웹 입력 상태는 갱신되며 단순 MANUAL↔AUTO 전환에서는 현재 입력을 유지한다. AUTO 이전에 MCU로 보냈던 패킷을 재사용하는 것이 아니라 진입 이후 새 패킷을 계속 송신한다. 초기 포트 연결의 0.55초 대기, 송수신 주기, MCU의 AUTO 진입 버퍼 폐기 및 모션 스케줄 때문에 물리적 무지연을 보장하지는 않는다. AUTO 전환마다 0.55초 대기를 다시 시작하지 않는다.

- 일반 키보드: W/S 선속도는 최대값까지 1초, 놓으면 같은 변화율로 0에 복귀한다. A/D는 새 키 누름마다 좌/우 한 단계로 조향을 바꾼다. 좌5…중앙0…우5의 11단계이며 각도는 단계 × 최대각/5이다. MCU 부호 기준 좌가 양수다. 키 자동 반복은 무시하고, 키를 놓아도 단계는 유지한다.
- PIVOT 키보드: A/D 각속도는 누르는 동안 증가하고 놓으면 같은 변화율로 복귀한다. 최대값 기준 1초이며 W/S는 사용하지 않는다.
- 마우스/터치: 일반 모드의 가로=조향·세로=선속도, PIVOT의 가로=각속도다. 위치를 즉시 목표로 사용하며 놓으면 최대값 기준 2초의 변화율로 복귀한다. 중심 데드밴드는 5%다.
- 입력 우선권: 먼저 시작한 키보드/마우스가 우선한다. 일반 키보드의 조향 단계가 0이 아니면 속도가 0이고 키를 놓았어도 키보드 소유권을 유지한다. 무시된 키/드래그는 새로 시작해야 한다. W+A 같은 키 조합은 가능하다.
- P 및 UI 모드 버튼: 누른 키나 드래그가 있으면 무시한다. 키를 놓은 뒤에는 목표가 아직 0으로 복귀 중이거나 조향 단계가 남아 있어도 전환을 요청할 수 있다. 입력을 전부 0으로 초기화하고 기존 모드의 0 목표를 보낸 뒤 아래 확인 절차를 기다린다. 완료 후 새 모드에서 새 입력이 필요하며, 일반 복귀의 조향 단계는 0이다.

- 초기 최대값: 2m/s, 0.845rad, 5rad/s. 숫자 입력칸에서 편집 후 `최대값 적용` 또는 Enter로 반영하며 변경은 중립에서만 가능하다. 입력 중인 값은 20Hz 서버 응답으로 덮어쓰지 않는다. 연결 전에도 값을 저장할 수 있고 같은 페이지에서 연결하면 반영한다. 새 페이지 로드 시에는 기본값으로 시작한다. 웹 입력 ramp는 MCU의 실제 가감속·조향 제한과 별개다.

### 모드 전환의 정지 확인

정지 요청 전 관측한 MCU 상태의 연결·세션과 새 seq 관측 횟수(host revision)를 기준으로, 다음 조건을 모두 만족하는 이후 피드백을 기다린다.

1. 최신 MCU 유효 운용 모드가 AUTO이며 시작 대기/POWERDOWN이 아님.
2. 같은 연결·세션에서 새로운 MCU seq의 상태가 관측됨. 집계가 동일 샘플을 반복 발행하는 것은 새 확인으로 세지 않음.
3. 목표 유효 bit4 및 적용 지령 유효 bit11이 1.
4. 기존 요청 운동 모드(bit12)와 기존 적용 모드가 일치하고 요청 v/θ/ω가 모두 0.
5. 적용 선속도와 PIVOT 각속도가 0.

이후 일반/PIVOT을 바꾸고 입력을 다시 초기화한다. 확인 전에는 기존 모드의 0 목표를 유지하며 시간 경과만으로 전환하지 않는다. AUTO 외 모드에서는 0·disable로 대기하고, AUTO가 되면 기존 모드의 정상 정지 목표(enable=1)부터 보낸다. 전환 대기 중 새 주행 입력·추가 P 요청은 무시한다.

이는 MCU 생성 지령 기반 확인이며 실제 휠 정지 또는 개별 명령 ACK가 아니다. 0x87에는 명령 수락 seq echo가 없으므로 특정 요청과의 엄밀한 일대일 대응은 보장하지 않는다. STEERING/SETTLING 등 적용 지령 무효 상태의 0은 정지 확인에 사용하지 않는다.

서버 `teleop.py`가 입력 중재와 ramp를 수행한다. `/ws/control`은 정규화 축 x/y와 source/active, 일반 키보드의 steer_delta(-1/0/+1), mode/limits 요청, 정상 stop, estop/clear_estop, heartbeat를 받는다. 입력 이벤트는 증가하는 event_id와 최근 서버 응답 token을 포함한다. token이 watchdog보다 오래되면 세션을 닫아 지연된 요청의 재생을 줄인다. 응답 control_state는 owner, pivot, neutral, 웹 입력, 실제 outgoing, enabled, authority, limits, steering_step, switching/pending_pivot, input_epoch, estop, control_signal_estop, token, 마지막 처리 event_id를 담는다. 입력·모드 요청은 최신 input_epoch도 포함하며 모드 전환·캐시 초기화 이전의 요청은 폐기한다.

브라우저 heartbeat와 목표 송신은 20Hz다. 0.3초 브라우저 입력 만료·WebSocket 단절·서버 송신 지연 시 세션을 닫고 enable=0을 요청한다. RC 모드 변경·MCU 피드백 만료만으로 웹 세션을 닫지는 않는다. 피드백 만료나 연결/CONTROL 세션 경계 변경에서는 입력·조향 단계를 초기화하고 0·disable로 대기한다. 진행 중인 모드 전환은 새 피드백으로 정지 확인을 다시 시작한다. 단순 RC 모드 변경은 기존 웹 입력을 유지한다. 브리지의 명령 만료는 별도 0.3초이며 MCU는 수락 명령 기준 500ms timeout을 사용한다. 탭 숨김/창 포커스 이탈도 연결을 닫는다. 다시 연결하고 새 입력을 해야 하며 이전 목표를 재생하지 않는다. 이들은 물리적 정지 확인이 아니다.

`중립 복귀`는 조향 단계 0과 속도 정상 ramp, `구동 해제`는 세션 종료/enable=0이다. `비상정지`는 AUTO의 TQ-OFF와 비상 조향 자세를 요청하며 일반 정지와 다르다. host estop은 세션 재연결이나 timeout으로 자동 해제하지 않고 별도 해제 버튼을 사용한다. RC MANUAL/PIVOT을 강제로 정지시키는 기능은 아니다.

## MCU 제어 신호 상실 비상 정지

Wheel-Dragoon `8bf301e`의 FAILSAFE(5)와 flags bit5 의미 확장을 지원한다. 웹에는 현재 운용 모드와 비상정지 상태만 표시하고 사용법·복구 안내·USB 이상 횟수 화면은 추가하지 않는다. 조작 안내 문구도 상태 표시와 분리하여 문서에서 제공한다.

`control.py`의 `control_signal_estop`은 원시 wire 필드가 아니라 기존 상태 조합에서 계산한 값이다. mode=5이거나, 복구 중 mode=POWERDOWN(3)·state=ESTOP(3)·flags bit5/7이 모두 활성인 경우에만 이 경로로 판단한다. typed ROS 메시지는 원래 mode/state/flags를 보존하고 웹 상태 JSON과 control_state에 파생 bool을 제공한다.

이 상태에서는 웹 입력과 대기 중인 일반/PIVOT 전환을 초기화하고 0·disable을 발행한다. 입력·모드 변경·웹 estop 해제 요청은 받아들이지 않으며 해당 해제 버튼도 비활성화한다. 펌웨어의 RC POWERDOWN → STOP 복구 후 세션 경계에서 다시 초기화하므로 이전 키/드래그/조향 단계가 재생되지 않는다. 복구 완료와 AUTO 재진입 후 새로 조작한다.

MCU 제어 신호 상실 비상 정지를 host estop으로 자동 래치하지 않는다. 호스트의 명시적 비상정지와 AUTO에서 관측된 host estop은 기존 host 래치로 유지하되, 공유 bit5를 수신했다는 이유만으로 두 경로를 합치지 않는다. 따라서 물리적 MCU 복구 뒤 불필요한 웹 estop 해제를 요구하지 않는다. 별도로 눌렀던 host estop은 여전히 명시적으로 해제해야 한다.

수신기 failsafe로 USB AUTO를 유지하는 중 웹 비상정지를 누르면 host estop이 활성화되어 MCU의 AUTO 유지 조건도 해제된다. 이때 MCU는 제어 신호 상실 비상 정지를 래치하고 릴레이를 차단한다. RC POWERDOWN → STOP으로 MCU를 복구한 뒤 웹 host estop도 별도로 해제해야 한다. 웹 비상정지 요청은 유효한 제어 연결에서 전달되며, 통신 단절 시 버튼 조작만으로 MCU 수신을 보장하지 않는다.

수신기 failsafe 중에도 MCU가 정상 USB AUTO 권한을 유지하면 mode=2를 보내므로 웹의 enable과 현재 입력은 그대로 유지된다. 이 경우 현재 프로토콜로 RC 무선 연결 정상/유실을 구분할 수 없으므로 정상 RC 링크라고 표시하거나 유실 배지를 추정하지 않는다. USB 이상 연속/누적 횟수와 복구 중립화 전용 상태도 wire에 없으며, 이를 새 측정값처럼 만들지 않는다. 상세 복구·PWM·이상 한계는 [브리지 문서](../my_car_mcu_bridge/README.md#수신기-failsafe와-제어-신호-상실-복구)를 따른다.

## Capture-to-display latency estimate

Each camera footer shows `지연 ≈123ms`, measuring capture time to the browser's **expected** presentation time, rather than RTT or decoder time alone. Synthetic sources use the distinct `생성 ≈…ms` label. The value is an estimate, not a measurement of physical monitor scanout/light emission.

Capture provenance:

- Picamera2 obtains pixels and metadata from the same `capture_request`, releases the request in `finally`, and converts `SensorTimestamp` (CLOCK_BOOTTIME, first-pixel readout) to the server monotonic clock. `ExposureTime` is subtracted to estimate the first row's exposure start. This is not a single exposure instant for the entire rolling-shutter frame.
- ROS raw/compressed sources use the image's `header.stamp`, mapped once to server monotonic time and cached with the decoded frame. This requires the publisher to stamp actual acquisition and share a synchronized system time domain with the web node. Zero/future/different-epoch headers and simulated ROS time are unavailable; the web node cannot verify publisher-side timestamp accuracy. Republishing an old frame retains its old capture time.
- Array-only/custom sources without capture timestamps show `지연 —`; synthetic sources report generation time, not camera capture time.

To avoid aiortc/RTP internals or unreliable out-of-band frame pairing, the encoder input gets a 32-pixel footer containing a 256x32 monochrome capture-time code (magic/provenance, uint64 monotonic microseconds, CRC32). Camera pixels are preserved. This adds a small frame copy, 32 encoded rows and decoder readback work; it is not zero-cost. Unknown metadata is explicitly encoded as unavailable to keep dimensions stable. Sources narrower than 256 pixels are unsupported. The browser decodes only this small region at up to 4 Hz and clips the appended footer out of the displayed video. Codec corruption fails the checksum and shows an unavailable value rather than guessing.

A read-only, uncached `/time` endpoint provides server receive/send monotonic milliseconds. The browser samples five short HTTP round trips on connection and every ten seconds while videos are active, retaining the lowest-RTT sample younger than 30 seconds. It estimates clock offset using the round-trip midpoint. Asymmetric paths introduce uncertainty (roughly up to half the residual round trip, apart from timestamp/scheduling errors); this is described in the value's tooltip. `requestVideoFrameCallback().expectedDisplayTime` supplies the estimated display endpoint. Unsupported browsers, stale displayed frames (1.5 seconds), expired clock samples and invalid time codes show `—`. Clock samples are discarded across visibility changes. No test execution is implied by this implementation; validation must be requested separately.

References: [Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf), [sensor timestamp/exposure clarification](https://github.com/raspberrypi/picamera2/issues/821), [video frame callback metadata](https://wicg.github.io/video-rvfc/).
