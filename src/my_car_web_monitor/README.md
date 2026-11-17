# my_car_web_monitor

`web_monitor_node`는 ROS 피드백·LiDAR·영상 소스를 브라우저에 제공한다. 현재 주행 제어는 비활성이다. `RosControlBridge`라는 내부 클래스명과 `/control/*` 경로는 남아 있지만 `/cmd_vel` publisher를 만들지 않는다.

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
| 구독 | `/telemetry` | `my_car_interfaces/msg/RobotTelemetry`, reliable / volatile depth 10 |
| 구독 | `/scan` | `sensor_msgs/msg/LaserScan`, best-effort / volatile depth 1 |
| 구독 | `CAMERA_STREAMS`의 ROS 이미지 토픽 | Image 또는 CompressedImage, 시청 중 구독 |

웹 노드는 시리얼 포트를 열지 않는다. `/telemetry`는 별도 `telemetry_aggregator`가 20Hz로 발행하며, 메시지 정의·집계 규칙은 [인터페이스](../my_car_interfaces/README.md)와 [브리지](../my_car_mcu_bridge/README.md)를 따른다. 제어·오도메트리·실측 조향 JointState는 발행하지 않는다.

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

상단에는 상태 수신 여부와 RC 모드·모션 단계·구동 허용·조향 보정 상태를 한 줄로 표시한다. 전압 A/B와 목표·적용 지령을 가로로 배치한다. 목표/적용은 각각 선속도 m/s, 중앙 조향각 rad, PIVOT 각속도 rad/s를 표시한다.

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

제어 관련 설정은 코드에 남아 있지만 현재 제어 전송에는 사용하지 않는다. `CMD_VEL_TOPIC=/cmd_vel`, `CONTROL_LINEAR_SPEED=2.0`, `CONTROL_ANGULAR_SPEED=3.0`, 각 축 MIN=0.0, DEFAULT=0.2/0.3, `CONTROL_WATCHDOG_TIMEOUT=0.3`이 기본값이다. 속도 설정은 여전히 시작 시 유한한 `0 ≤ min ≤ default ≤ max` 검사를 수행한다.

## HTTP / WebSocket

| 경로 | 현재 동작 |
| --- | --- |
| `GET /` / `/static/*` | 브라우저 UI·정적 파일 |
| `GET /health` | 웹 서버 응답, MCU 연결 보장은 아님 |
| `GET /time` | 서버 monotonic 시각, 영상 지연 추정용 |
| `GET /streams` | 영상 소스 목록 |
| `POST /offer` | stream_id/sdp/type로 WebRTC 협상 |
| `GET /control/config` | 남아 있는 속도 설정 조회 |
| `GET /control/status` | 최신 웹 상태 JSON 조회 |
| `/ws/status` | 읽기 전용 상태 스트림 |
| `/ws/scan` | 읽기 전용 LiDAR 바이너리 스트림 |
| `/ws/control` | 비활성 오류 JSON 전송 후 코드 1008로 종료 |

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

현재 shutdown handler는 `control_bridge.stop()`을 호출하지만 해당 메서드는 수신 전용 모드의 RuntimeError를 발생시킨다. 따라서 종료 정리에서 예외가 발생하고 뒤의 영상 정리가 건너뛰어질 수 있다. 이는 코드상 남아 있는 제약이며 이 문서 작업에서는 코드를 변경하지 않았다.

## Capture-to-display latency estimate

Each camera footer shows `지연 ≈123ms`, measuring capture time to the browser's **expected** presentation time, rather than RTT or decoder time alone. Synthetic sources use the distinct `생성 ≈…ms` label. The value is an estimate, not a measurement of physical monitor scanout/light emission.

Capture provenance:

- Picamera2 obtains pixels and metadata from the same `capture_request`, releases the request in `finally`, and converts `SensorTimestamp` (CLOCK_BOOTTIME, first-pixel readout) to the server monotonic clock. `ExposureTime` is subtracted to estimate the first row's exposure start. This is not a single exposure instant for the entire rolling-shutter frame.
- ROS raw/compressed sources use the image's `header.stamp`, mapped once to server monotonic time and cached with the decoded frame. This requires the publisher to stamp actual acquisition and share a synchronized system time domain with the web node. Zero/future/different-epoch headers and simulated ROS time are unavailable; the web node cannot verify publisher-side timestamp accuracy. Republishing an old frame retains its old capture time.
- Array-only/custom sources without capture timestamps show `지연 —`; synthetic sources report generation time, not camera capture time.

To avoid aiortc/RTP internals or unreliable out-of-band frame pairing, the encoder input gets a 32-pixel footer containing a 256x32 monochrome capture-time code (magic/provenance, uint64 monotonic microseconds, CRC32). Camera pixels are preserved. This adds a small frame copy, 32 encoded rows and decoder readback work; it is not zero-cost. Unknown metadata is explicitly encoded as unavailable to keep dimensions stable. Sources narrower than 256 pixels are unsupported. The browser decodes only this small region at up to 4 Hz and clips the appended footer out of the displayed video. Codec corruption fails the checksum and shows an unavailable value rather than guessing.

A read-only, uncached `/time` endpoint provides server receive/send monotonic milliseconds. The browser samples five short HTTP round trips on connection and every ten seconds while videos are active, retaining the lowest-RTT sample younger than 30 seconds. It estimates clock offset using the round-trip midpoint. Asymmetric paths introduce uncertainty (roughly up to half the residual round trip, apart from timestamp/scheduling errors); this is described in the value's tooltip. `requestVideoFrameCallback().expectedDisplayTime` supplies the estimated display endpoint. Unsupported browsers, stale displayed frames (1.5 seconds), expired clock samples and invalid time codes show `—`. Clock samples are discarded across visibility changes. No test execution is implied by this implementation; validation must be requested separately.

References: [Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf), [sensor timestamp/exposure clarification](https://github.com/raspberrypi/picamera2/issues/821), [video frame callback metadata](https://wicg.github.io/video-rvfc/).
