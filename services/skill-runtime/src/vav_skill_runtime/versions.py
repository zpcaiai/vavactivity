"""Small deterministic SemVer range resolver for manifest constraints."""

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


class VersionConstraintError(ValueError):
    pass


def parse_version(value: str) -> Version:
    try:
        version = Version(value)
    except InvalidVersion as exc:
        raise VersionConstraintError(f"invalid semantic version: {value}") from exc
    if len(version.release) != 3:
        raise VersionConstraintError(f"semantic version must contain major.minor.patch: {value}")
    return version


def normalize_constraint(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("^"):
        base = parse_version(stripped[1:])
        upper_major = base.major + 1 if base.major else 0
        upper_minor = 0 if base.major else base.minor + 1
        return f">={base},<{upper_major}.{upper_minor}.0"
    tokens = stripped.replace(",", " ").split()
    normalized = ",".join(tokens)
    if normalized and normalized[0].isdigit():
        normalized = f"=={normalized}"
    return normalized


def satisfies(version: str, constraint: str) -> bool:
    parsed = parse_version(version)
    try:
        return parsed in SpecifierSet(normalize_constraint(constraint))
    except InvalidSpecifier as exc:
        raise VersionConstraintError(f"invalid version constraint: {constraint}") from exc
