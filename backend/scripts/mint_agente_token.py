"""Out-of-band token minting for the `agente-ia` service user (tickets-ai-triage PR 6).

Mints a 90-day JWT for `sub="agente-ia"` and prints it once for the operator
to copy into the AI agent's environment. This script does NOT touch the ORM
or the database at all — `create_access_token` only encodes a signed JWT
in-process, so there is no SQLAlchemy mapper-registry risk here (contrast
with `scripts/audit_transiciones_tickets.py`, which DOES query the ORM and
therefore needs `from app.models import *` / `from app.tickets.models import
*`, per `alembic/env.py`'s precedent). Skipping those imports here is
deliberate, not an oversight — importing them would be cargo-culting a fix
for a failure mode this script cannot hit.

The script never commits the token to the repo and never logs it (no
`logger.*` call anywhere in this module) — it is written to stdout exactly
once, for the operator to copy and store outside version control (e.g. the
agent host's environment, a secrets manager). Anyone with this token can act
as `agente-ia` for up to 90 days; treat it like a password.

Usage:
    cd backend && SECRET_KEY=... DATABASE_URL=... ERP_BASE_URL=... \\
        ./venv/bin/python -m scripts.mint_agente_token
"""

from __future__ import annotations

from datetime import timedelta

from app.core.security import create_access_token

AGENTE_USERNAME = "agente-ia"
TOKEN_LIFETIME = timedelta(days=90)


def mint() -> str:
    """Return a freshly signed JWT for the `agente-ia` service user."""
    return create_access_token({"sub": AGENTE_USERNAME}, TOKEN_LIFETIME)


def main() -> None:
    token = mint()
    print("Token for 'agente-ia' (90 days) — copy now, this is shown only once:")
    print(token)
    print(
        "\nStore it in the agent host's environment (never in the repo, never in a "
        "log). Revoke access at any time by setting usuario.activo=False for "
        "'agente-ia', no redeploy required."
    )


if __name__ == "__main__":
    main()
