"""Input ownership, latched keyboard steering, and stop-before-mode switching."""
import math


class TeleopState:
    def __init__(self, ramp_seconds=1.0, mouse_return_seconds=2.0):
        self.ramp_seconds = ramp_seconds
        self.mouse_return_seconds = mouse_return_seconds
        self.limits = [2.0, 0.845, 5.0]
        self.pivot = False
        self.pending_pivot = None
        self.input_epoch = 0
        self._clear_inputs()

    def _clear_inputs(self):
        self.values = [0.0, 0.0, 0.0]
        self.steering_step = 0  # Positive = left, negative = right; MCU sign convention.
        self.owner = None
        self.active = False
        self.axes = [0.0, 0.0]
        self.blocked = {"keyboard": False, "mouse": False}
        self.held = {"keyboard": False, "mouse": False}
        self.input_epoch += 1

    @property
    def switching(self):
        return self.pending_pivot is not None

    @property
    def neutral(self):
        return not self.switching and self.owner is None and not any(self.values)

    def reset(self):
        self.pending_pivot = None
        self._clear_inputs()

    def suspend(self):
        # Lost telemetry/connection boundary: discard motion, preserve a pending stop.
        self._clear_inputs()

    def set_limits(self, values):
        if not self.neutral:
            raise ValueError("중립에서만 최대값을 변경할 수 있습니다")
        if len(values) != 3 or any(type(x) not in (int, float) or not math.isfinite(x)
                or not 0 < x <= cap for x, cap in zip(values, (2.0, 0.845, 5.0))):
            raise ValueError("최대값이 MCU 허용 범위를 벗어났습니다")
        self.limits = list(values)

    def request_mode(self, pivot):
        if type(pivot) is not bool:
            raise ValueError("pivot must be boolean")
        # A held key/drag wins over P, including ignored competing inputs.
        if self.switching or any(self.held.values()):
            return False
        if pivot == self.pivot:
            return True
        self._clear_inputs()
        self.pending_pivot = pivot
        return True

    def complete_mode(self):
        if not self.switching:
            return
        self.pivot = self.pending_pivot
        self.pending_pivot = None
        self._clear_inputs()

    def return_to_neutral(self):
        self.active = False
        self.axes = [0.0, 0.0]
        self.steering_step = 0
        self.blocked = {"keyboard": True, "mouse": True}

    def input(self, source, active, x, y, steer_delta=0):
        if source not in self.blocked or type(active) is not bool:
            raise ValueError("잘못된 입력 방식")
        if any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1 for v in (x, y)):
            raise ValueError("입력 축은 -1..1 범위여야 합니다")
        if type(steer_delta) is not int or steer_delta not in (-1, 0, 1):
            raise ValueError("조향 단계 변화는 -1, 0, 1이어야 합니다")
        if steer_delta and (source != "keyboard" or self.pivot or not active):
            raise ValueError("일반 모드의 새 키 누름에서만 조향 단계를 바꿀 수 있습니다")
        self.held[source] = active
        if not active:
            self.blocked[source] = False
        if self.switching:
            if active:
                self.blocked[source] = True
            return False
        if self.owner not in (None, source):
            if active:
                self.blocked[source] = True
            return False
        if self.blocked[source] and active:
            return False
        if self.owner is None:
            if not active:
                return True
            self.owner = source
        self.active = active
        self.axes = [x, y] if active else [0.0, 0.0]
        if source == "keyboard" and not self.pivot:
            self.steering_step = max(-5, min(5, self.steering_step + steer_delta))
        return True

    def tick(self, dt):
        if self.switching:
            # A zero target in the OLD mode lets the MCU perform normal braking.
            self.values = [0.0, 0.0, 0.0]
            return self.values
        dt = max(0.0, min(dt, 0.1))
        x, y = self.axes
        targets = [0.0, 0.0, x * self.limits[2]] if self.pivot else [y * self.limits[0], x * self.limits[1], 0.0]
        if self.owner == "keyboard" and not self.pivot:
            targets[1] = self.steering_step * self.limits[1] / 5
        for index, target in enumerate(targets):
            if ((self.owner == "mouse" and self.active)
                    or (self.owner == "keyboard" and not self.pivot and index == 1)):
                self.values[index] = target
            else:
                duration = self.mouse_return_seconds if self.owner == "mouse" else self.ramp_seconds
                step = self.limits[index] * dt / duration
                delta = target - self.values[index]
                self.values[index] += max(-step, min(step, delta))
                if abs(target - self.values[index]) < 1e-9:
                    self.values[index] = target
        if not self.active and not any(self.values) and self.steering_step == 0:
            self.owner = None
        return self.values

    def snapshot(self):
        return {"owner": self.owner, "pivot": self.pivot, "neutral": self.neutral,
                "linear": self.values[0], "steering": self.values[1], "angular": self.values[2],
                "limits": self.limits, "steering_step": self.steering_step,
                "switching": self.switching, "pending_pivot": self.pending_pivot,
                "input_epoch": self.input_epoch}
