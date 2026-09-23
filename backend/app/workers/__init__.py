"""Generic LISTEN/NOTIFY worker runtime (ventas-ml-rediseno, design D4, D6).

`app/workers/registry.py` ships an EMPTY handler list in PR2 (idle worker,
no consumers yet) -- PR3+ registers the `order_metrics.*` handlers. This
package is a no-cron replacement: `python -m app.workers.run` under systemd
unit `pricing-worker.service`, never crontab.
"""

from __future__ import annotations
