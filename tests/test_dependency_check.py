from cisco_to_ansible import parse_config, build_playbook, run_dependency_check


def _cfg(text: str):
    return parse_config(text)


def test_vrf_referenced_before_defined_warns():
    text = "\n".join([
        "interface GigabitEthernet0/0",
        " vrf forwarding MGMT",
        "!",
        "vrf definition MGMT",
        " address-family ipv4",
        " exit-address-family",
        "!",
    ])
    cfg = _cfg(text)
    build_playbook(cfg, host="sw", source_file="t.txt")
    warnings = run_dependency_check(cfg)
    # VRF definitions are Phase 3; interfaces are Phase 4. Even when the source
    # has the interface before the VRF definition, the emission re-orders them so
    # the VRF is defined before it is referenced. No warning expected.
    assert not any("vrf forwarding MGMT" in w for w in warnings), warnings


def test_flow_monitor_referenced_before_defined_warns():
    text = "\n".join([
        "interface GigabitEthernet0/0",
        " ip flow monitor MON1 input",
        "!",
        "flow monitor MON1",
        " cache timeout active 60",
        "!",
    ])
    cfg = _cfg(text)
    run_dependency_check(cfg)
    # The new ordering (interfaces are Phase 4, flow_monitors are Phase 3)
    # means the reference is now AFTER the definition. No warning.
    warnings = run_dependency_check(cfg)
    assert not any("flow monitor MON1" in w for w in warnings), warnings


def test_bgp_neighbor_route_map_undefined_warns():
    text = "\n".join([
        "router bgp 65001",
        " neighbor 10.0.0.2 route-map MISSING in",
        "!",
    ])
    cfg = _cfg(text)
    warnings = run_dependency_check(cfg)
    assert any("route-map MISSING" in w for w in warnings), warnings


def test_all_known_good_config_has_no_warnings():
    from pathlib import Path
    ROOT = Path(__file__).parent.parent
    text = (ROOT / "tests" / "fixtures" / "FRS-QRS-SW01-2026-04-14.txt").read_text(encoding="utf-8")
    cfg = _cfg(text)
    warnings = run_dependency_check(cfg)
    assert warnings == [], f"expected no warnings, got: {warnings}"
