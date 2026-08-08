from pathlib import Path

from vav.core.evidence import junit_evidence


def test_junit_evidence_rejects_entity_declarations(tmp_path: Path) -> None:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        """<?xml version="1.0"?>
<!DOCTYPE testsuite [<!ENTITY payload "unsafe">]>
<testsuite tests="1" failures="0" errors="0"><testcase name="&payload;"/></testsuite>
""",
        encoding="utf-8",
    )
    command_path = tmp_path / "command.json"
    command_path.write_text('{"status":"PASS"}', encoding="utf-8")

    result = junit_evidence(junit_path, command_path)

    assert result["status"] == "FAIL"
    assert result["reason"].startswith("invalid JUnit evidence:")
