"""Standalone helper process for PR3.T6c: claims a real batch of
`ml_order_metrics_dirty` rows against the test PostgreSQL database (pointed
to via the `DATABASE_URL` env var the parent test sets), starts a real
`HeartbeatThread` renewing those claims, prints `READY <order_ids>` once
claimed, then blocks forever so the parent test can SIGKILL it mid-batch.

Not a pytest test module (leading underscore, no `test_` prefix) -- invoked
only as `python _t6c_subprocess_worker.py <order_id> [<order_id> ...] <lease_seconds>`.
"""

from __future__ import annotations

import sys
import time
from datetime import timedelta

from app.services.order_metrics.queue import claim_dirty
from app.workers.heartbeat import HeartbeatThread


def main() -> None:
    *order_id_args, lease_seconds_arg = sys.argv[1:]
    expected_order_ids = {int(v) for v in order_id_args}
    lease = timedelta(seconds=float(lease_seconds_arg))

    claims = claim_dirty(limit=len(expected_order_ids), lease=lease, worker_id="t6c-doomed-worker")
    claimed_ids = {c.order_id for c in claims}
    if claimed_ids != expected_order_ids:
        print(f"CLAIM_MISMATCH expected={expected_order_ids} got={claimed_ids}", flush=True)
        sys.exit(1)

    held_tokens = {str(c.claim_token) for c in claims}
    heartbeat = HeartbeatThread(
        worker_name="t6c-doomed-worker",
        interval=lease.total_seconds() / 6,
        token_provider=lambda: held_tokens,
    )
    heartbeat.start()

    print(f"READY {' '.join(str(i) for i in sorted(claimed_ids))}", flush=True)

    # Simulate being mid-batch: block forever. The parent test SIGKILLs this
    # process, which kills the heartbeat thread too (no graceful shutdown,
    # no final release) -- exactly what a crashed worker looks like.
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
