from cisco_to_ansible import validate_ip_formats, parse_config


def _cfg(s: str):
    return parse_config(s)


def test_valid_config_has_no_warnings():
    cfg = _cfg("\n".join([
        "interface Vlan10",
        " ip address 10.0.0.1 255.255.255.0",
        "!",
        "ip dhcp pool D",
        " network 10.0.0.0 255.255.255.0",
        " default-router 10.0.0.1",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert errs == [] and warns == []


def test_malformed_ipv4_is_error():
    cfg = _cfg("\n".join([
        "interface Vlan10",
        " ip address 10.0.300.1 255.255.255.0",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("10.0.300.1" in e for e in errs), errs


def test_non_contiguous_mask_is_warning():
    cfg = _cfg("\n".join([
        "interface Vlan10",
        " ip address 10.0.0.1 255.0.255.0",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("mask" in w.lower() for w in warns), warns


def test_network_statement_with_host_bits_is_warning():
    cfg = _cfg("\n".join([
        "ip dhcp pool D",
        " network 10.0.0.5 255.255.255.0",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("host bits" in w for w in warns), warns


def test_default_router_equals_broadcast_is_warning():
    cfg = _cfg("\n".join([
        "ip dhcp pool D",
        " network 10.0.0.0 255.255.255.0",
        " default-router 10.0.0.255",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("broadcast" in w.lower() for w in warns), warns


def test_radius_server_address_must_be_valid():
    cfg = _cfg("\n".join([
        "radius server S1",
        " address ipv4 not.an.ip auth-port 1812 acct-port 1813",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("not.an.ip" in e for e in errs), errs


def test_ntp_server_hostname_is_not_validated():
    cfg = _cfg("ntp server ntp.example.com")
    errs, warns = validate_ip_formats(cfg)
    assert errs == [] and warns == []


def test_bgp_router_id_invalid_is_error():
    cfg = _cfg("\n".join([
        "router bgp 65001",
        " bgp router-id 999.0.0.1",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("999.0.0.1" in e for e in errs), errs


def test_dhcp_pool_invalid_mask_is_error():
    """Malformed mask on a DHCP pool network is an error, not just a warning."""
    cfg = _cfg("\n".join([
        "ip dhcp pool P",
        " network 10.0.0.0 255.0.256.0",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert any("10.0.0.0 255.0.256.0" in e for e in errs), (errs, warns)


def test_interface_slash_32_loopback_no_host_warning():
    """A /32 loopback address is not flagged as network or broadcast."""
    cfg = _cfg("\n".join([
        "interface Loopback0",
        " ip address 10.1.1.1 255.255.255.255",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert errs == []
    assert all("network address" not in w and "broadcast address" not in w
               for w in warns), warns


def test_interface_slash_31_point_to_point_no_host_warning():
    """A /31 point-to-point address using network number is not flagged."""
    cfg = _cfg("\n".join([
        "interface GigabitEthernet0/0",
        " ip address 10.0.0.0 255.255.255.254",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    assert errs == []
    assert all("network address" not in w and "broadcast address" not in w
               for w in warns), warns


def test_dhcp_pool_default_router_before_network():
    """default-router validates against the pool subnet regardless of child-line order."""
    cfg = _cfg("\n".join([
        "ip dhcp pool P",
        " default-router 10.0.1.5",
        " network 10.0.0.0 255.255.255.0",
        "!",
    ]))
    errs, warns = validate_ip_formats(cfg)
    # default-router 10.0.1.5 is NOT in 10.0.0.0/24, must produce a warning
    assert any("not in the pool subnet" in w for w in warns), (errs, warns)


def test_name_server_error_uses_standard_format():
    """name-server validation errors use the standard line-prefix format."""
    cfg = _cfg("ip name-server 999.1.1.1")
    errs, warns = validate_ip_formats(cfg)
    assert any(e.startswith("ERROR: line 0 (ip name-server):") for e in errs), errs
