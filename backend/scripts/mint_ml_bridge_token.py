"""Out-of-band token minting for the `ml-webhook-bridge` service user
(ml-activity-receiver slice 1).

Mints a 90-day JWT for `sub="ml-webhook-bridge"` and prints it once for the
operator to copy into the ml-webhook bridge's environment. This script does
NOT touch the ORM or the database at all -- `create_access_token` only
encodes a signed JWT in-process, so there is no SQLAlchemy mapper-registry
risk here (same reasoning as `scripts/mint_agente_token.py`, which this
script is modelled on).

The script never commits the token to the repo and never logs it (no
`logger.*` call anywhere in this module) -- it is written to stdout exactly
once, for the operator to copy and store outside version control (e.g. the
bridge host's environment, a secrets manager). Anyone with this token can
act as `ml-webhook-bridge` for up to 90 days; treat it like a password.

The minted token is scoped to exactly `ml_ops.ingest` via the seeded role
(`20260909_seed_ml_bridge_service_user.py`) -- it is denied on every other
`ml-ventas-ops` route (`ml_ops.ver`, `ml_ops.gestionar`).

Usage:
    cd backend && SECRET_KEY=... DATABASE_URL=... \\
        .venv/bin/python -m scripts.mint_ml_bridge_token
"""

from __future__ import annotations

from datetime import timedelta

from app.core.security import create_access_token

BRIDGE_USERNAME = "ml-webhook-bridge"
TOKEN_LIFETIME = timedelta(days=90)


def mint() -> str:
    """Return a freshly signed JWT for the `ml-webhook-bridge` service user."""
    return create_access_token({"sub": BRIDGE_USERNAME}, TOKEN_LIFETIME)


def main() -> None:
    token = mint()
    print("Token for 'ml-webhook-bridge' (90 days) -- copy now, this is shown only once:")
    print(token)
    print(
        "\nStore it in the ml-webhook bridge host's environment (never in the repo, "
        "never in a log). It is scoped to exactly 'ml_ops.ingest'. Revoke access at "
        "any time by setting usuario.activo=False for 'ml-webhook-bridge', no "
        "redeploy required."
    )


if __name__ == "__main__":
    main()
