"""Per-request timing of the view endpoints: the measure-first mechanism of the design (§4.6, §5.5).

A `Timer` measures named stages (count, page, facets, status...) and reports them twice: as one `pubml.view`
log line (what the volume test and the production measurement read) and as a `Server-Timing` header (what the
R6 measurement script prints without access to the server's log).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

logger = logging.getLogger("pubml.view")


class Timer:
    def __init__(self, endpoint: str, clock: Callable[[], float] = time.perf_counter) -> None:
        self.endpoint = endpoint
        self._clock = clock
        self._started = clock()
        self.stages: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = self._clock()
        try:
            yield
        finally:
            elapsed = (self._clock() - started) * 1000
            self.stages[name] = round(self.stages.get(name, 0.0) + elapsed, 1)

    def server_timing(self) -> str:
        return ", ".join(f"{name};dur={ms}" for name, ms in self.stages.items())

    def emit(self, **fields: Any) -> str:
        total = round((self._clock() - self._started) * 1000, 1)
        parts = [f"pubml.view endpoint={self.endpoint} total_ms={total}"]
        parts += [f"{name}_ms={ms}" for name, ms in self.stages.items()]
        parts += [f"{name}={value}" for name, value in fields.items()]
        line = " ".join(parts)
        logger.info(line)
        return line
