from cisco_to_ansible import Task, render_task


def test_task_dataclass_renders_yaml():
    t = Task(
        name="Configure hostname",
        module="cisco.ios.ios_hostname",
        params=[("config", {"hostname": "SW01"}), ("state", "merged")],
    )
    lines = render_task(t, indent=4)
    joined = "\n".join(lines)
    assert "- name: " in joined
    assert "cisco.ios.ios_hostname:" in joined
    assert "hostname: SW01" in joined


def test_task_defaults():
    t = Task(name="x", module="cisco.ios.ios_config")
    assert t.params == []
    assert t.origin == []


import re
from pathlib import Path
import subprocess, sys

ROOT = Path(__file__).parent.parent


def _run_tool(tmp_path, flags=()):
    out = tmp_path / "gen.yml"
    result = subprocess.run(
        [sys.executable, str(ROOT / "cisco_to_ansible.py"),
         str(ROOT / "tests" / "fixtures" / "FRS-QRS-SW01-2026-04-14.txt"),
         "-o", str(out), *flags],
        capture_output=True, text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    return out.read_text(encoding="utf-8")


def _first_index(text: str, pattern: str) -> int:
    """Return character offset of first match, or raise."""
    m = re.search(pattern, text)
    assert m is not None, f"pattern not found: {pattern!r}"
    return m.start()


def test_vrf_definition_precedes_vrf_forwarding(tmp_path):
    text = _run_tool(tmp_path)
    def_pos = _first_index(text, r'parents:\s*"vrf definition Mgmt-vrf"')
    use_pos = _first_index(text, r'"vrf forwarding Mgmt-vrf"')
    assert def_pos < use_pos, "VRF must be defined before any interface references it"


def test_flow_monitor_precedes_interface_reference(tmp_path):
    text = _run_tool(tmp_path)
    def_pos = _first_index(text, r'parents:\s*"flow monitor WUG-In"')
    use_pos = _first_index(text, r'"ip flow monitor WUG-In input"')
    assert def_pos < use_pos


def test_acls_precede_route_maps(tmp_path):
    text = _run_tool(tmp_path)
    acl_pos = _first_index(text, r'parents:\s*"ip access-list standard TPX-INGRESS-IN"')
    rm_pos = _first_index(text, r'parents:\s*"route-map TPX-INGRESS-IN permit 10"')
    assert acl_pos < rm_pos


def test_route_maps_precede_bgp(tmp_path):
    text = _run_tool(tmp_path)
    rm_pos = _first_index(text, r'parents:\s*"route-map TPX-INGRESS-IN permit 10"')
    bgp_pos = _first_index(text, r'parents:\s*"router bgp 64610"')
    assert rm_pos < bgp_pos


def test_stp_mode_precedes_interface_enable(tmp_path):
    text = _run_tool(tmp_path)
    stp_pos = _first_index(text, r'"spanning-tree mode rapid-pvst"')
    iface_pos = _first_index(text, r'cisco\.ios\.ios_interfaces:')
    assert stp_pos < iface_pos, "STP mode must be set before interfaces come up"


def test_snmp_view_precedes_community(tmp_path):
    text = _run_tool(tmp_path)
    view_pos = _first_index(text, r'"snmp-server view NO_BAD_SNMP iso included"')
    comm_pos = _first_index(text, r'"snmp-server community qu1nngr0up view NO_BAD_SNMP RO"')
    assert view_pos < comm_pos


def test_radius_servers_precede_aaa_auth(tmp_path):
    text = _run_tool(tmp_path)
    rad_pos = _first_index(text, r'parents:\s*"radius server FRS-SRVR05"')
    aaa_pos = _first_index(text, r'"aaa authentication login default local"')
    assert rad_pos < aaa_pos
