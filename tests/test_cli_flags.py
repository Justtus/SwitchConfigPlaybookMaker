import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "cisco_to_ansible.py"
CLEAN = ROOT / "tests" / "fixtures" / "FRS-QRS-SW01-2026-04-14.txt"


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _run(args, *, expect_out=None):
    result = subprocess.run([sys.executable, str(SCRIPT), *args],
                            capture_output=True, text=True, cwd=str(ROOT))
    return result


def test_clean_config_exits_zero(tmp_path):
    out = tmp_path / "out.yml"
    r = _run([str(CLEAN), "-o", str(out)])
    assert r.returncode == 0, r.stderr


def test_warning_without_strict_exits_zero(tmp_path):
    cfg = _write(tmp_path, "bad.txt", "\n".join([
        "ip dhcp pool P",
        " network 10.0.0.0 255.255.255.0",
        " default-router 10.0.1.99",
        "!",
    ]))
    out = tmp_path / "out.yml"
    r = _run([str(cfg), "-o", str(out)])
    assert r.returncode == 0, r.stderr
    assert "WARNING" in r.stderr


def test_warning_with_strict_exits_one(tmp_path):
    cfg = _write(tmp_path, "bad.txt", "\n".join([
        "ip dhcp pool P",
        " network 10.0.0.0 255.255.255.0",
        " default-router 10.0.1.99",
        "!",
    ]))
    out = tmp_path / "out.yml"
    r = _run([str(cfg), "-o", str(out), "--strict"])
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert out.exists(), "YAML must still be written under --strict"


def test_malformed_ipv4_exits_two(tmp_path):
    cfg = _write(tmp_path, "bad.txt", "\n".join([
        "interface Vlan10",
        " ip address 10.0.300.1 255.255.255.0",
        "!",
    ]))
    out = tmp_path / "out.yml"
    r = _run([str(cfg), "-o", str(out)])
    assert r.returncode == 2
    assert not out.exists(), "YAML must NOT be written on hard error"


def test_no_validate_skips_checks(tmp_path):
    cfg = _write(tmp_path, "bad.txt", "\n".join([
        "ip dhcp pool P",
        " network 10.0.0.0 255.255.255.0",
        " default-router 10.0.1.99",
        "!",
    ]))
    out = tmp_path / "out.yml"
    r = _run([str(cfg), "-o", str(out), "--no-validate"])
    assert r.returncode == 0
    assert "WARNING" not in r.stderr


def test_stderr_summary_on_clean_run(tmp_path):
    out = tmp_path / "out.yml"
    r = _run([str(CLEAN), "-o", str(out)])
    assert "Dependency check:" in r.stderr
    assert "IP format check:" in r.stderr
    assert "Subnet membership check:" in r.stderr
    assert "Wrote" in r.stderr


def test_no_summary_with_no_validate(tmp_path):
    out = tmp_path / "out.yml"
    r = _run([str(CLEAN), "-o", str(out), "--no-validate"])
    assert "Dependency check:" not in r.stderr
    # but still report "Wrote" to stderr? Per spec, the "Wrote" line is part
    # of the summary block and omitted under --no-validate. The existing
    # stdout "Wrote ..." line stays (not in stderr).
