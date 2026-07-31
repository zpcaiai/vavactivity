from vav.modules.content.domain import ContentStatus, TranslationStatus


def test_publication_states_are_stable() -> None:
    assert ContentStatus.DRAFT == "draft"
    assert ContentStatus.IN_REVIEW == "in_review"
    assert ContentStatus.PUBLISHED == "published"
    assert TranslationStatus.OUTDATED == "outdated"
