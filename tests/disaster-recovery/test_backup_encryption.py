from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRYPTO = ROOT / "scripts/backup/backup_crypto.py"


def test_backup_encryption_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    source = tmp_path / "backup.dump"
    encrypted = tmp_path / "backup.dump.vavenc"
    restored = tmp_path / "restored.dump"
    key = tmp_path / "key"
    source.write_bytes((b"production-backup-fixture\0" * 4096) + b"end")
    key.write_bytes(b"a" * 32)
    subprocess.run(
        [
            sys.executable,
            str(CRYPTO),
            "encrypt",
            str(source),
            str(encrypted),
            "--key-file",
            str(key),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(CRYPTO),
            "decrypt",
            str(encrypted),
            str(restored),
            "--key-file",
            str(key),
        ],
        check=True,
    )
    assert restored.read_bytes() == source.read_bytes()

    payload = bytearray(encrypted.read_bytes())
    payload[len(payload) // 2] ^= 1
    encrypted.write_bytes(payload)
    failed = subprocess.run(
        [
            sys.executable,
            str(CRYPTO),
            "decrypt",
            str(encrypted),
            str(restored),
            "--key-file",
            str(key),
        ],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0


def test_chaos_entrypoint_requires_explicit_local_confirmation() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/disaster-recovery/inject-compose-failure.sh")],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "SERVICE": "api"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CHAOS_CONFIRM" in result.stderr
