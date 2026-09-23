"""RED/GREEN -- `WorkerRuntime` exits non-zero when its heartbeat thread is
dead or stalled (ventas-ml-rediseno PR2.T4b, design D4 step 5 "Thread death
detection"): the main loop must stop starting new work and exit with code
70 so systemd (`Restart=always`) restarts the process -- a dead heartbeat
means the worker can no longer prove liveness, so any claim it holds is a
fair charge against it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.workers.runtime import HEARTBEAT_DEATH_EXIT_CODE, WorkerRuntime


class TestHeartbeatDeathExitsNonZero:
    def test_unhealthy_heartbeat_triggers_sys_exit_70(self, caplog) -> None:
        runtime = WorkerRuntime(registry=[])
        runtime.heartbeat = MagicMock()
        runtime.heartbeat.is_healthy.return_value = False

        with caplog.at_level("CRITICAL", logger="app.workers.runtime"):
            with pytest.raises(SystemExit) as exc_info:
                runtime._check_heartbeat_or_die()

        assert exc_info.value.code == HEARTBEAT_DEATH_EXIT_CODE == 70
        assert any("heartbeat" in record.message.lower() for record in caplog.records)
        assert any(record.levelname == "CRITICAL" for record in caplog.records)

    def test_healthy_heartbeat_never_exits(self) -> None:
        runtime = WorkerRuntime(registry=[])
        runtime.heartbeat = MagicMock()
        runtime.heartbeat.is_healthy.return_value = True

        runtime._check_heartbeat_or_die()  # must not raise

    def test_no_heartbeat_started_yet_never_exits(self) -> None:
        runtime = WorkerRuntime(registry=[])
        runtime.heartbeat = None

        runtime._check_heartbeat_or_die()  # must not raise
