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
