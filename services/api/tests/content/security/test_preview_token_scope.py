from vav.modules.identity.security import opaque_token, sha256_token


def test_preview_token_hash_is_not_reversible_or_structured() -> None:
    raw_token = opaque_token()
    token_hash = sha256_token(raw_token)

    assert raw_token not in token_hash
    assert len(token_hash) == 64
