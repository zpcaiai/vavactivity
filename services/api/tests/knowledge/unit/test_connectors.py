from vav.modules.knowledge.connectors import _public_text


def test_connector_projection_excludes_private_and_learner_fields() -> None:
    rendered = _public_text(
        {
            "title": "Published course",
            "learning_outcomes": ["Respect boundaries"],
            "answer": "learner private answer",
            "submission": "private assignment",
            "private_note": "mentor-only note",
            "email": "private@example.com",
        }
    )
    assert "Published course" in rendered
    assert "Respect boundaries" in rendered
    assert "learner private answer" not in rendered
    assert "private assignment" not in rendered
    assert "mentor-only note" not in rendered
    assert "private@example.com" not in rendered
