from cisco_to_ansible import parse_blocks


def test_parse_blocks_returns_line_numbers():
    lines = [
        "hostname test",                       # 1
        "!",                                   # 2
        "vlan 10 name Data",                   # 3
        "!",                                   # 4
        "interface Vlan10",                    # 5
        " description DATA_SVI",               # 6
        " ip address 10.0.0.1 255.255.255.0",  # 7
        "!",                                   # 8
    ]
    blocks = parse_blocks(lines)
    assert blocks[0] == ("hostname test", 1, [])
    assert blocks[1] == ("vlan 10 name Data", 3, [])
    assert blocks[2] == (
        "interface Vlan10",
        5,
        [
            ("description DATA_SVI", 6),
            ("ip address 10.0.0.1 255.255.255.0", 7),
        ],
    )


from cisco_to_ansible import classify_block


def test_classify_block_dispatches_known_headers():
    cases = [
        ("hostname SW01", "hostname"),
        ("ip domain name example.com", "domain"),
        ("ip name-server 10.0.0.1", "name_server"),
        ("vlan 10 name Data", "vlan_inline"),
        ("interface Vlan10", "interface"),
        ("vrf definition Mgmt-vrf", "vrf"),
        ("ip dhcp pool VOICE", "dhcp_pool"),
        ("ip dhcp excluded-address 10.0.0.1 10.0.0.10", "dhcp_excluded"),
        ("flow record WUG-In", "flow_record"),
        ("flow exporter WUG", "flow_exporter"),
        ("flow monitor WUG-In", "flow_monitor"),
        ("ip access-list standard NAME", "acl"),
        ("ip access-list extended NAME", "acl"),
        ("route-map TPX permit 10", "route_map"),
        ("router bgp 65001", "bgp"),
        ("radius server FRS-SRVR05", "radius_server"),
        ("snmp-server view NO_BAD_SNMP iso included", "snmp_view"),
        ("snmp-server community abc view NO_BAD_SNMP RO", "snmp_community"),
        ("archive", "archive"),
        ("redundancy", "redundancy"),
        ("transceiver type all", "transceiver"),
        ("control-plane", "control_plane"),
        ("line con 0", "line_block"),
        ("line vty 0 4", "line_block"),
        ("banner login ^C", "banner_header"),
        ("aaa new-model", "aaa_new_model"),
        ("aaa authentication login default local", "aaa_auth"),
        ("aaa authorization exec default local", "aaa_auth"),
        ("aaa session-id common", "aaa_new_model"),
        ("spanning-tree mode rapid-pvst", "stp_global"),
        ("spanning-tree extend system-id", "stp_global"),
        ("ip routing", "ip_routing_global"),
        ("ip forward-protocol nd", "ip_routing_global"),
        ("username quinn privilege 15 secret 9 xyz", "user"),
        ("logging buffered 40960", "logging"),
        ("logging host 10.0.0.1", "logging"),
        ("logging source-interface Vlan200", "source_interface_global"),
        ("ip radius source-interface Vlan200", "source_interface_global"),
        ("ntp server ntp.example.com", "ntp"),
        ("ip ftp username foo", "ip_service"),
        ("ip http authentication aaa", "ip_service"),
        ("no ip http server", "ip_service"),
        ("no ip http secure-server", "ip_service"),
        ("clock timezone pst -8 0", "base_service"),
        ("service timestamps debug datetime msec", "base_service"),
        ("no service pad", "base_service"),
        ("service password-encryption", "base_service"),
        ("platform management port rate-limt-enabled", "base_service"),
        ("no platform punt-keepalive disable-kernel-core", "base_service"),
        ("diagnostic bootup level minimal", "base_service"),
        ("memory free low-watermark processor 79468", "base_service"),
        ("login on-success log", "base_service"),
        ("no device-tracking logging theft", "base_service"),
        ("something unknown here", "misc"),
    ]
    for header, expected in cases:
        assert classify_block(header) == expected, f"{header!r} -> {classify_block(header)!r}, expected {expected!r}"


from cisco_to_ansible import parse_config


def test_parse_config_buckets_blocks():
    text = "\n".join([
        "hostname SW01",
        "!",
        "vlan 10 name Data",
        "!",
        "vrf definition MGMT",
        " address-family ipv4",
        " exit-address-family",
        "!",
        "interface Vlan10",
        " ip address 10.0.0.1 255.255.255.0",
        "!",
        "ip access-list standard ACL1",
        " permit any",
        "!",
        "route-map RM1 permit 10",
        " match ip address ACL1",
        "!",
        "router bgp 65001",
        " neighbor 10.0.0.2 remote-as 65002",
        "!",
    ])
    cfg = parse_config(text)
    assert cfg.hostname == "SW01"
    assert cfg.vlans == [{"vlan_id": 10, "name": "Data"}]
    assert len(cfg.vrfs) == 1
    assert cfg.vrfs[0][0] == "vrf definition MGMT"
    assert len(cfg.interfaces) == 1
    assert len(cfg.acls) == 1
    assert len(cfg.route_maps) == 1
    assert len(cfg.bgp) == 1
