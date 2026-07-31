import pytest
from pydantic import ValidationError

from vav.modules.content.domain import Action


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/html,x", "relative"])
def test_content_actions_reject_unsafe_links(href: str) -> None:
    with pytest.raises(ValidationError):
        Action(label="unsafe", href=href)
