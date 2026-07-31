import pytest
from pydantic import TypeAdapter, ValidationError

from vav.modules.content.domain import ContentBlock

adapter = TypeAdapter(ContentBlock)


def test_structured_call_to_action_accepts_safe_local_link() -> None:
    block = adapter.validate_python(
        {
            "id": "block-1",
            "type": "call_to_action",
            "version": 1,
            "data": {
                "title": "开始",
                "button": {"label": "注册", "href": "/zh-CN/auth/register"},
            },
        }
    )

    assert block.type == "call_to_action"


@pytest.mark.parametrize(
    "document",
    [
        {"type": "doc", "content": [{"text": "<script>alert(1)</script>"}]},
        {"type": "doc", "content": [{"href": "javascript:alert(1)"}]},
        {"type": "doc", "content": [{"text": '<a onclick="steal()">x</a>'}]},
    ],
)
def test_rich_text_rejects_executable_markup(document: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "id": "block-1",
                "type": "rich_text",
                "version": 1,
                "data": {"document": document},
            }
        )
