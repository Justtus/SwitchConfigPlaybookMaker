"""Golden-file regression: cisco_to_ansible produces byte-identical YAML."""
from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "cisco_to_ansible.py"
FIXTURE_IN = ROOT / "tests" / "fixtures" / "FRS-QRS-SW01-2026-04-14.txt"
FIXTURE_OUT = ROOT / "tests" / "fixtures" / "FRS-QRS-SW01.baseline.yml"


def test_baseline_matches_fixture(tmp_path):
    out = tmp_path / "generated.yml"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE_IN), "-o", str(out)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"tool failed: {result.stderr}"
    actual = out.read_text(encoding="utf-8")
    expected = FIXTURE_OUT.read_text(encoding="utf-8")
    if actual != expected:
        diff = list(difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="baseline",
            tofile="generated",
            n=3,
        ))
        excerpt = "\n".join(diff[:40])
        pytest.fail(f"Generated YAML diverged from baseline fixture:\n{excerpt}")


FIRMWARE_OUT = ROOT / "tests" / "fixtures" / "FRS-QRS-SW01.with-firmware.yml"


def test_firmware_fixture_matches(tmp_path):
    out = tmp_path / "generated.yml"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE_IN),
         "-o", str(out), "--with-upgrade"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == FIRMWARE_OUT.read_text(encoding="utf-8")
