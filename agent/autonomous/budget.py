from __future__ import annotations

import time


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, *, max_steps: int, timeout_seconds: int):
        self.max_steps = max(1, int(max_steps))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.steps_used = 0
        self._started = time.monotonic()

    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self.steps_used)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started

    def remaining_seconds(self) -> float:
        return max(0.0, float(self.timeout_seconds) - self.elapsed_seconds())

    def consume_step(self) -> None:
        self.steps_used += 1
        if self.steps_used > self.max_steps:
            raise BudgetExceeded("max_steps_exceeded")
        if self.elapsed_seconds() > float(self.timeout_seconds):
            raise BudgetExceeded("timeout_exceeded")

