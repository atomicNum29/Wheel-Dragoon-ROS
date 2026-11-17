# 현재 구현 안내

이 경로에 있던 과거 계획·작업 보고서는 [보관 기록](archive/documentation_before_split_rewrite/agent/ros2_motor_bridge_update_report.md)으로 옮겼다. 당시 패킷·경로·테스트 결과는 현재 구현의 사용법이나 검증 근거가 아니다.

현재 구조는 다음과 같다.

- `my_car_interfaces`: WheelFeedback, VoltageFeedback, McuStatus, LinkState, RobotTelemetry 정의.
- `my_car_mcu_bridge/mcu_bridge_node`: 최신 0x85/86/87 v1 수신 후 개별 typed topic 즉시 발행. 제어 송신 없음.
- `telemetry_aggregator`: latest-value 집계 `/telemetry` 20Hz 발행.
- `my_car_web_monitor`: `/telemetry` 구독 후 웹 경계에서 JSON 변환. 웹 제어 비활성.

[브리지 구현·설정](../src/my_car_mcu_bridge/README.md) · [메시지 정의](../src/my_car_interfaces/README.md) · [웹 동작·설정](../src/my_car_web_monitor/README.md)

이 안내는 현재 코드를 설명한다. 빌드·테스트·실물 검증은 이번 문서 정리에서 수행하지 않았다.
