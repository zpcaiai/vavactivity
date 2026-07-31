from vav.modules.identity.domain import SessionStatus, UserStatus


def test_identity_states_are_stable_contract_values() -> None:
    assert UserStatus.PENDING_VERIFICATION == "pending_verification"
    assert UserStatus.ACTIVE == "active"
    assert SessionStatus.REPLACED == "replaced"
    assert SessionStatus.REVOKED == "revoked"
