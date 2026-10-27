# ML publications: freshness alert

`ml_publications.freshness` (worker-ml, every minute, no ML call) measures how late the store is on what ML
told it changed, and sends the owner a WhatsApp past a target.

## What is measured

A notification leaves a queue entry with the time ML sent it and the resources it asks for. A resource of that
entry is **late** when it was not fetched since the notification and has been due for longer than its target.
Due means the notification, or the resource's last check plus its minimum age (`min_age_seconds`), whichever is
later: waiting out the minimum age is the store's choice, not a delay.

| Resource | Target |
|---|---|
| Publication status (`items`) | 2 min |
| Prices, sale price, promotions | 5 min |
| Competition (catalog listings only) | 5 min |
| Description | 6 h |
| Family | 24 h |
| Visits | 25 h (age of the last check on active items; the sweep laps them once a day) |

Only the resources in `bundle_resources` are measured; visits only while `sweep.enabled` is on. Stock (the
publication's available quantity) is not measured. Targets live in `ML_PUB_FRESHNESS_TARGET_SECONDS`.

The handler's `worker_job_state.detail` holds the last report: per resource `late` and `oldest_late_seconds`,
and per queue lane the waiting count and the oldest wait.

## Alerts

A resource that becomes late sends one WhatsApp; it is not repeated while it stays late, and one more message
says when everything is back. An alert wabot did not take is tried again on the next tick (`detail.alert`).

The message goes to `WABOT_OWNER_TO` with `WABOT_TOKEN` (backend `.env`). wabot sends a message without a
recipient to the users' group, so nothing is sent until `WABOT_OWNER_TO` is set (`detail.alert:
"not_configured"`).
