import pytest
from pydantic import ValidationError

from vav.modules.content.schemas import NavigationItemInput


def test_navigation_external_link_requires_safe_absolute_url() -> None:
    with pytest.raises(ValidationError):
        NavigationItemInput(
            internal_name="unsafe",
            link_type="external",
            external_url="javascript:alert(1)",
            localizations=[{"locale": "en", "label": "Unsafe"}],
        )


def test_navigation_localization_locales_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        NavigationItemInput(
            internal_name="duplicate",
            link_type="route",
            route_name="about",
            localizations=[
                {"locale": "en", "label": "About"},
                {"locale": "en", "label": "Company"},
            ],
        )
