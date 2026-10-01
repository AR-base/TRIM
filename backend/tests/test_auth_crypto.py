import pytest

from trim.auth import Role, TokenAuthenticator, TokenConfigError, hash_token, new_token, parse_token_config
from trim.crypto import SecretBox, SecretBoxError


def test_token_roundtrip():
    token = new_token()
    assert token.startswith("trim_") and len(token) > 40
    auth = TokenAuthenticator(f"ana:admin:{hash_token(token)},rev:reviewer:{hash_token('other')}")
    p = auth.authenticate(token)
    assert p.name == "ana" and p.role is Role.admin and p.can_change_access()
    assert auth.authenticate("other").role is Role.reviewer
    assert not auth.authenticate("other").can_change_access()


@pytest.mark.parametrize("presented", [None, "", "wrong", "x" * 300])
def test_rejects_bad_tokens(presented):
    auth = TokenAuthenticator(f"ana:admin:{hash_token('good')}")
    assert auth.authenticate(presented) is None


@pytest.mark.parametrize("raw", ["ana:admin", "ana:root:" + "a" * 64, "ana:admin:short", "bad name:admin:" + "a" * 64])
def test_rejects_bad_config(raw):
    with pytest.raises(TokenConfigError):
        parse_token_config(raw)


def test_empty_config_allows_nobody():
    assert parse_token_config(" , ") == []
    assert TokenAuthenticator("").authenticate("anything") is None


def test_secret_box_roundtrip_and_tamper():
    box = SecretBox(SecretBox.generate_key())
    ct = box.encrypt('{"type": "service_account"}')
    assert b"service_account" not in ct
    assert box.decrypt(ct) == '{"type": "service_account"}'
    with pytest.raises(SecretBoxError):
        box.decrypt(ct[:-4] + b"AAAA")
    with pytest.raises(SecretBoxError):
        SecretBox(SecretBox.generate_key()).decrypt(ct)


@pytest.mark.parametrize("key", ["", "not-a-key"])
def test_secret_box_rejects_bad_keys(key):
    with pytest.raises(SecretBoxError):
        SecretBox(key)
