"""
Tests for scripts/mint_agente_token.py (tickets-ai-triage PR 6, task 6.8).

This script does NOT touch the ORM: `create_access_token` only signs a JWT
in-process (no DB query, no SQLAlchemy relationship resolution), so the
standalone-script mapper-registry trap documented in obs #1323/#1350
(`InvalidRequestError: expression 'Usuario' failed to locate a name`,
`scripts/audit_transiciones_tickets.py`'s real production bug) does not
apply here — there is nothing for `from app.models import *` to fix, and a
subprocess-in-a-fresh-interpreter test would prove nothing this direct-import
test doesn't already prove. A plain import + call is sufficient.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_mint_agente_token.py -v
"""

from datetime import UTC, datetime, timedelta

from app.core.security import decode_token
from scripts.mint_agente_token import AGENTE_USERNAME, TOKEN_LIFETIME, main, mint


def test_mint_returns_a_valid_token_for_agente_ia():
    token = mint()

    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == AGENTE_USERNAME == "agente-ia"


def test_mint_token_expires_in_about_90_days():
    assert TOKEN_LIFETIME == timedelta(days=90)

    token = mint()
    payload = decode_token(token)
    exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    delta = exp - datetime.now(UTC)

    # Small tolerance for test execution time, still proves ~90 days, not
    # the default ACCESS_TOKEN_EXPIRE_MINUTES a caller forgetting the
    # `expires_delta` argument would silently fall back to.
    assert timedelta(days=89, hours=23) < delta <= timedelta(days=90)


def test_main_prints_the_token_once_and_never_logs_it(capsys, caplog):
    main()

    captured = capsys.readouterr()
    assert "agente-ia" in captured.out

    lines = [line for line in captured.out.splitlines() if line.strip()]
    token_line = lines[1]  # line 0 is the operator-facing label
    payload = decode_token(token_line)
    assert payload is not None
    assert payload["sub"] == "agente-ia"

    # Never through the logging module — only via print(), which the
    # operator sees once and this script never re-emits (no logger.* calls
    # anywhere in scripts/mint_agente_token.py).
    assert caplog.records == []
