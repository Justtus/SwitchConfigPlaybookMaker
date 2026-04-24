from cisco_to_ansible import validate_subnet_membership, parse_config


def _cfg(s: str):
    return parse_config(s)


def test_default_router_outside_pool_is_warning():
    cfg = _cfg("\n".join([
        "ip dhcp pool P",
        " network 10.0.0.0 255.255.255.0",
        " default-router 10.0.1.5",
        "!",
    ]))
    hard, soft = validate_subnet_membership(cfg)
    assert any("not in the pool subnet" in w for w in hard), hard


def test_host_lease_outside_all_pools_is_soft_warning():
    cfg = _cfg("\n".join([
        "ip dhcp pool P1",
        " network 10.0.0.0 255.255.255.0",
        "!",
        "ip dhcp pool LEASE",
        " host 192.168.99.1 255.255.255.0",
        "!",
    ]))
    hard, soft = validate_subnet_membership(cfg)
    assert any("not in any defined DHCP pool network" in w for w in soft), soft


def test_excluded_address_outside_all_pools_is_soft_warning():
    cfg = _cfg("\n".join([
        "ip dhcp excluded-address 192.168.77.1 192.168.77.10",
        "ip dhcp pool P1",
        " network 10.0.0.0 255.255.255.0",
        "!",
    ]))
    hard, soft = validate_subnet_membership(cfg)
    assert any("192.168.77.1" in w for w in soft), soft


def test_bgp_neighbor_not_directly_connected_is_soft_warning():
    cfg = _cfg("\n".join([
        "interface Vlan2",
        " ip address 10.0.0.25 255.255.255.248",
        "!",
        "router bgp 65001",
        " neighbor 192.168.200.200 remote-as 65002",
        "!",
    ]))
    hard, soft = validate_subnet_membership(cfg)
    assert any("192.168.200.200" in w and "directly connected" in w for w in soft), soft


def test_known_good_sample_config_has_no_hard_warnings():
    from pathlib import Path
    ROOT = Path(__file__).parent.parent
    text = (ROOT / "tests" / "fixtures" / "FRS-QRS-SW01-2026-04-14.txt").read_text(encoding="utf-8")
    cfg = _cfg(text)
    hard, soft = validate_subnet_membership(cfg)
    assert hard == [], f"unexpected hard warnings: {hard}"
