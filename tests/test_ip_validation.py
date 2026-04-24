from cisco_to_ansible import validate_ip_formats, parse_config, IPValidationError


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
