"""Session-local communication accounting; independent consecutive RX/TX errors."""
import logging

logger = logging.getLogger("my_car_web_monitor.server")


class ControlHealth:
    def __init__(self):
        self.consecutive = {}
        self.total = 0
        self.clean = 0

    def error(self, channel, reason, count=1):
        self.clean = 0
        self.total += count
        self.consecutive[channel] = self.consecutive.get(channel, 0) + count
        limit = self.consecutive[channel] >= 3 or self.total >= 10
        logger.warning(
            "Control communication error: channel=%s reason=%s count=%d consecutive=%d cumulative=%d stop=%s",
            channel, reason, count, self.consecutive[channel], self.total, limit)
        return limit

    def success(self, channel, *, exchange=False):
        self.consecutive[channel] = 0
        # Count fresh client exchanges, not independent server TX ticks, for decay.
        if exchange:
            self.clean += 1
            if self.clean == 100:
                self.clean = 0
                if self.total:
                    self.total -= 1
                    logger.info("Control communication recovery: cumulative=%d", self.total)
