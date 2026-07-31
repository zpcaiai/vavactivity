from vav.modules.identity.security import hmac_token, opaque_token, sha256_token


def test_opaque_credentials_are_only_persistable_as_hashes() -> None:
    raw_refresh = opaque_token("vav_rt_")
    raw_verification = opaque_token()

    assert raw_refresh not in hmac_token(raw_refresh)
    assert raw_verification not in sha256_token(raw_verification)
    assert len(hmac_token(raw_refresh)) == 64
    assert len(sha256_token(raw_verification)) == 64
