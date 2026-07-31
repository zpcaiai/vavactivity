from vav.core.config import get_settings


def test_user_and_admin_audiences_are_distinct() -> None:
    settings = get_settings()

    assert settings.auth_user_audience != settings.auth_admin_audience
