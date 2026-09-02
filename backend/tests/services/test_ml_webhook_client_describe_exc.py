import httpx
from app.services.ml_webhook_client import _describe_exc


def test_a_timeout_is_not_logged_as_a_bare_colon():
    """`httpx.ReadTimeout` has an empty `str()`. The old `f"...: {e}"` produced
    `Error obteniendo shipment 123:` with nothing after it, which is what made
    the proxy hang look like an error with no cause."""
    assert str(httpx.ReadTimeout("")) == ""
    assert _describe_exc(httpx.ReadTimeout("")) == "ReadTimeout"


def test_a_real_message_is_kept_and_qualified():
    assert _describe_exc(ValueError("boom")) == "ValueError: boom"
