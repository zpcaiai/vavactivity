from urllib.parse import urlparse


def is_safe_local_redirect(target: str) -> bool:
    parsed = urlparse(target)
    return (
        not parsed.scheme
        and not parsed.netloc
        and target.startswith("/")
        and not target.startswith("//")
    )


def redact(value: str, visible_suffix: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible_suffix:
        return "*" * len(value)
    return "*" * (len(value) - visible_suffix) + value[-visible_suffix:]
