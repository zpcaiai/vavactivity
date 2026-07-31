from uuid import uuid4

import pytest

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.modules.identity.security import AccessTokenService


def test_access_token_enforces_audience() -> None:
    settings = get_settings()
    service = AccessTokenService(settings)
    token = service.issue(
        user_id=uuid4(),
        session_id=uuid4(),
        audience=settings.auth_user_audience,
        auth_version=1,
        rbac_version=1,
    )

    claims = service.decode(token, settings.auth_user_audience)
    assert claims.audience == settings.auth_user_audience

    with pytest.raises(VavError) as error:
        service.decode(token, settings.auth_admin_audience)
    assert error.value.code == "TOKEN_INVALID"
