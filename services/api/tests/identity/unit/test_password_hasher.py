from vav.common.exceptions import VavError
from vav.modules.identity.security import PasswordHasher, PasswordPolicy


def test_argon2id_hash_does_not_contain_password() -> None:
    password = "a thoughtful passphrase"
    password_hash = PasswordHasher().hash(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(password_hash, password)
    assert not PasswordHasher().verify(password_hash, "wrong passphrase")


def test_password_policy_rejects_email_and_common_password() -> None:
    policy = PasswordPolicy()

    for password in ("member@example.com", "passwordpassword"):
        try:
            policy.validate(password, "member@example.com")
        except VavError as exc:
            assert exc.code == "PASSWORD_POLICY_VIOLATION"
        else:
            raise AssertionError("weak password should be rejected")
