"""Golden-file regression: cisco_to_ansible produces byte-identical YAML."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
    assert actual == expected, "Generated YAML diverged from baseline fixture"
