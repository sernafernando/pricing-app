"""Runtime settings of the ML publications store (design D19).

Flags and tunables live in `ml_pub_settings` so an operator can change them
without a deploy; handlers read them at the start of every run and at every
batch boundary. The environment (`app.core.config.settings`) only supplies the
DEFAULT for a key that has no row, so a fresh deploy is governed purely by the
all-off env defaults.

`ML_PUB_KILL_SWITCH` is environment-only on purpose: when set, every `*.enabled`
flag reads as disabled regardless of the database, and the database is not even
queried. A settings table that cannot be read also reads as disabled (fail
closed); tunables fall back to their env default instead.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Sequence

from app.core import database
from app.core.config import settings
from app.models.ml_publications import MlPubSetting

logger = logging.getLogger(__name__)

SOURCE_DB = "db"
SOURCE_ENV = "env"
SOURCE_KILL_SWITCH = "kill_switch"
SOURCE_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class Setting:
    key: str
    value: Any
    source: str


@dataclass(frozen=True)
class _Def:
    env_attr: str
    valid: Callable[[Any], bool]


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _int_between(low: int, high: int | None = None) -> Callable[[Any], bool]:
    def check(value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return value >= low and (high is None or value <= high)

    return check


def _positive_number(maximum: float) -> Callable[[Any], bool]:
    def check(value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return 0 < value <= maximum

    return check


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _scan_mode(value: Any) -> bool:
    return value in ("full", "rescan") and isinstance(value, str)


def _json_object(value: Any) -> bool:
    return isinstance(value, dict)


_FLAGS = (
    "refresh",
    "intake",
    "scan",
    "missed_feeds",
    "sweep",
    "events",
    "promotions",
    "links",
    "verify",
    "divergence",
)

# The allow-list: only these keys can be read from or written to `ml_pub_settings`.
# Env-only values (lease seconds, max attempts, intake batch, ...) are deliberately absent.
SETTING_DEFS: Dict[str, _Def] = {
    **{f"{flag}.enabled": _Def(f"ML_PUB_{flag.upper()}_ENABLED", _is_bool) for flag in _FLAGS},
    "bundle_resources": _Def("ML_PUB_BUNDLE_RESOURCES", _str_list),
    "intake.topics": _Def("ML_PUB_INTAKE_TOPICS", _json_object),
    "min_age_seconds": _Def("ML_PUB_MIN_AGE_SECONDS", _json_object),
    "scan.statuses": _Def("ML_PUB_SCAN_STATUSES", _str_list),
    "scan.next_mode": _Def("ML_PUB_SCAN_NEXT_MODE", _scan_mode),
    "sweep.statuses": _Def("ML_PUB_SWEEP_STATUSES", _str_list),
    "rate_per_sec": _Def("ML_PUB_RATE_PER_SEC", _positive_number(20)),
    "stock_rate_per_min": _Def("ML_PUB_STOCK_RATE_PER_MIN", _int_between(1, 100)),
    "bulk_max_ids": _Def("ML_PUB_BULK_MAX_IDS", _int_between(1, 20)),
    "low_lane_min_share": _Def("ML_PUB_LOW_LANE_MIN_SHARE", _positive_number(1)),
}


def _definition(key: str) -> _Def:
    try:
        return SETTING_DEFS[key]
    except KeyError:
        raise ValueError(f"unknown ml_pub setting {key!r}") from None


def _env_default(definition: _Def) -> Any:
    return copy.deepcopy(getattr(settings, definition.env_attr))


def _is_enabled_flag(key: str) -> bool:
    return key.endswith(".enabled")


def _resolve(key: str, definition: _Def, stored: Any, found: bool) -> Setting:
    if not found:
        return Setting(key, _env_default(definition), SOURCE_ENV)
    if not definition.valid(stored):
        logger.warning("ml_pub setting %s has an invalid stored value %r; using the env default", key, stored)
        return Setting(key, _env_default(definition), SOURCE_ENV)
    return Setting(key, stored, SOURCE_DB)


def get_settings(keys: Sequence[str]) -> Dict[str, Setting]:
    """Effective values for `keys` (kill switch, then DB row, then env default) in ONE
    short session, so a handler can read everything it needs at a batch boundary."""
    definitions = {key: _definition(key) for key in keys}
    if not definitions:
        return {}
    result: Dict[str, Setting] = {}
    to_read: List[str] = []
    for key in definitions:
        if _is_enabled_flag(key) and settings.ML_PUB_KILL_SWITCH:
            result[key] = Setting(key, False, SOURCE_KILL_SWITCH)
        else:
            to_read.append(key)
    if not to_read:
        return result
    try:
        with database.get_background_db() as session:
            rows = session.query(MlPubSetting).filter(MlPubSetting.key.in_(to_read)).all()
            stored = {row.key: copy.deepcopy(row.value) for row in rows}
    except Exception:
        logger.exception("ml_pub settings %s unreadable", to_read)
        for key in to_read:
            if _is_enabled_flag(key):
                result[key] = Setting(key, False, SOURCE_UNREADABLE)
            else:
                result[key] = Setting(key, _env_default(definitions[key]), SOURCE_ENV)
        return result
    for key in to_read:
        result[key] = _resolve(key, definitions[key], stored.get(key), key in stored)
    return result


def get_setting(key: str) -> Setting:
    """Effective value of one key; see `get_settings`."""
    return get_settings([key])[key]


def is_enabled(handler: str) -> bool:
    """True only when `<handler>.enabled` is on and nothing forces it off."""
    key = f"{handler}.enabled"
    if not _is_enabled_flag(key) or key not in SETTING_DEFS:
        raise ValueError(f"unknown ml_pub handler {handler!r}")
    return get_setting(key).value is True


def set_setting(key: str, value: Any, updated_by: str) -> None:
    """Upsert one allow-listed setting. Rejects unknown keys and invalid values."""
    definition = _definition(key)
    if not definition.valid(value):
        raise ValueError(f"invalid value for ml_pub setting {key!r}: {value!r}")
    with database.get_background_db() as session:
        session.merge(MlPubSetting(key=key, value=value, updated_by=updated_by, updated_at=datetime.now(timezone.utc)))
