# Cisco Playbook Ordering, Validation, and Firmware Preamble

**Status:** Draft, pending user review
**Date:** 2026-04-23
**Scope:** Changes to `cisco_to_ansible.py` to (1) emit Ansible tasks in a dependency-correct order, (2) validate the generated playbook and input IPs, and (3) optionally prepend a firmware-upgrade block.

---

## 1. Problem

`cisco_to_ansible.py` currently emits tasks in a fixed structural order (hostname → VLANs → interfaces → users → banner → logging/NTP → globals → raw blocks in source-file order). Against the sample `FRS-QRS-SW01-2026-04-14.txt` this produces a playbook with several concrete dependency problems:

1. **VRF referenced before defined.** The per-interface residue task for `GigabitEthernet0/0` issues `vrf forwarding Mgmt-vrf` before `vrf definition Mgmt-vrf` is applied. IOS rejects `vrf forwarding X` when X does not exist. Hard fail.
2. **Flow monitors referenced before defined.** Interfaces Gi1/0/10, Gi1/0/46, and Gi1/0/48 issue `ip flow monitor WUG-In/Out` before `flow record`, `flow exporter`, and `flow monitor` are created. Hard fail.
3. **BGP references route-maps that are not yet defined.** `router bgp 64610` is emitted before `route-map TPX-INGRESS-IN permit 10` because both are raw blocks and BGP appears earlier in the source file. IOS accepts this but the route-map is dormant until defined. Soft fail / idempotency gap.
4. **STP mode changes after ports come up.** `spanning-tree mode rapid-pvst` is bucketed into the "globals" task, which runs after interface enable. Ports briefly come up under default STP, then the mode changes. Transient risk (TCN flurry, brief blocking).
5. **Latent risk for generic use.** Radius servers are emitted after AAA authentication. This specific config uses `aaa authentication login default local`, so there is no break, but a future config using `group radius local` would fail.
6. **SNMP view/community ordering is accidentally correct.** The globals bucket preserves source-file order. If a future config listed `snmp-server community … view X` before `snmp-server view X …`, the emission would be broken.

The tool must also, on reasonable effort:

- Validate IP addresses and subnet masks it encounters during parsing.
- Validate that IPs given alongside subnets actually fall in those subnets.
- Warn on structural ordering mistakes that remain after the reorder fix (so future configs with novel dependency shapes are caught).
- Optionally prepend a firmware-upgrade block to the generated playbook so the switch can be upgraded from a USB-mounted image before configuration is applied.

## 2. Non-goals

- IPv6 validation. None appears in the current sample; defer to a later pass.
- Deep hostname/FQDN validation — the check distinguishes "looks like an IP" from "looks like a name" and only validates the former.
- Semantic validation of ACL rule syntax, policy-map internals, or route-map match/set correctness.
- StackWise / stacked-switch-aware firmware upgrade. Single chassis only.
- Install-mode firmware upgrade (IOS-XE `install add/activate/commit`). Bundle mode only.
- Rewriting the tool from procedural to class-based. The existing shape is fine.

## 3. Emission order (the fix)

Replace the single `raw_blocks` list with a set of named buckets populated during parsing, then emit them in the phases below. Within each bucket, source-file order is preserved.

### Phase 0 — Firmware upgrade (opt-in, see Section 6)

### Phase 1 — Identity & base services
1. `hostname`
2. Domain name + name-servers (`cisco.ios.ios_system`)
3. Global one-liners: `no service pad`, `service timestamps …`, `service password-encryption`, `platform …`, `clock …`, `memory low-watermark`, `diagnostic`, `login on-success log`, `no device-tracking …`

### Phase 2 — AAA & identity
Users emitted before AAA so `default local` fallback has creds. Radius servers emitted before AAA directives that might reference `group radius`.

4. `username …` (`cisco.ios.ios_user`)
5. `aaa new-model` + `aaa session-id common`
6. `radius server X` blocks
7. `aaa authentication …` / `aaa authorization …`

### Phase 3 — Forwarding primitives
Everything that gets *referenced* later by interfaces, protocols, or services.

8. `ip routing` / `ip forward-protocol nd`
9. VRF definitions
10. VLAN database (`cisco.ios.ios_vlans`)
11. **Spanning-tree mode + `spanning-tree extend system-id`** — moved from globals to here, before ports come up.
12. Standard + extended ACLs
13. Route-maps (after ACLs)
14. `flow record` → `flow exporter` → `flow monitor` (ordered within themselves)
15. SNMP views, then SNMP community
16. `ip dhcp excluded-address` lines
17. `ip dhcp pool …` blocks

### Phase 4 — Interfaces
18. Admin state + description (`cisco.ios.ios_interfaces`)
19. L2 switchport (`cisco.ios.ios_l2_interfaces`)
20. L3 addressing (`cisco.ios.ios_l3_interfaces`)
21. Per-interface residue: `vrf forwarding`, `ip flow monitor`, `spanning-tree portfast`, `auto qos`, `negotiation auto`, etc.

### Phase 5 — Services & protocols that need interfaces
22. `router bgp` (needs interfaces, ACLs, route-maps)
23. `ip radius source-interface VlanX`
24. `logging buffered` / `source-interface` / `host`
25. NTP servers
26. `ip ftp …` / `ip http …`

### Phase 6 — Management & housekeeping
27. Login banner
28. `line con 0` / `line aux 0` / `line vty 0 4` / `line vty 5 15`
29. `archive`
30. `redundancy`
31. `transceiver …`
32. `control-plane`

### Parser changes
Introduce typed buckets during parsing:

```
cfg = {
  'hostname': ..., 'domain_name': ..., 'name_servers': [...],
  'base_services': [...],                 # global services & one-liners in phase 1
  'users': [...],
  'aaa_new_model': [...],                 # phase 2.5
  'radius_servers': [(header, [children], line)],
  'aaa_auth': [...],                      # phase 2.7
  'ip_routing_globals': [...],            # phase 3.8
  'vrfs': [...],
  'vlans': [...],
  'stp_globals': [...],                   # phase 3.11
  'acls': [...],
  'route_maps': [...],
  'flow_records': [...], 'flow_exporters': [...], 'flow_monitors': [...],
  'snmp_views': [...], 'snmp_communities': [...],
  'dhcp_excluded': [...],
  'dhcp_pools': [...],
  'interfaces': [...],
  'bgp': [...],                           # phase 5.22
  'source_interface_globals': [...],      # phase 5.23
  'logging': [...],                       # phase 5.24
  'ntp_servers': [...],
  'ip_services': [...],                   # ftp, http — phase 5.26
  'banner': (kind, text),
  'line_blocks': [...],
  'archive': [...], 'redundancy': [...],
  'transceiver': [...], 'control_plane': [...],
  'misc_blocks': [...],                   # anything unrecognized, emitted last
}
```

Dispatch by matching `header` against specific prefixes. Unknown blocks go to `misc_blocks` and are emitted at the end of Phase 6 so they never accidentally precede something they reference.

## 4. Validation — dependency check

Post-emission static analysis over the generated task list. Walks tasks in order, maintains two sets:

- **Defined names** (VRFs, flow objects, ACLs, route-maps, radius servers, SNMP views, Vlan interfaces, VLAN IDs, local usernames).
- **Observed references** that need a defined name.

### Definition patterns

| Pattern | Records |
|---|---|
| `vrf definition NAME` | VRF NAME |
| `flow (record\|exporter\|monitor) NAME` | flow object NAME |
| `ip access-list (standard\|extended) NAME` | ACL NAME |
| `route-map NAME` | route-map NAME |
| `radius server NAME` | radius server NAME |
| `snmp-server view NAME …` | SNMP view NAME |
| `interface VlanN` | Vlan interface N |
| `vlan N …` (ios_vlans structured) | VLAN ID N |
| `username NAME` | user NAME |

### Reference patterns

| Pattern | Requires |
|---|---|
| `vrf forwarding X` | VRF X |
| `ip flow monitor X (input\|output)` | flow monitor X |
| `match ip address X` (within a route-map) | ACL X |
| `neighbor … route-map Y (in\|out)` | route-map Y |
| `snmp-server community … view V …` | SNMP view V |
| `ip radius source-interface VlanN` | Vlan interface N |
| `logging source-interface VlanN` | Vlan interface N |
| `aaa authentication … group radius …` | at least one radius server |
| `switchport access vlan N` / `switchport voice vlan N` / `switchport trunk native vlan N` | VLAN N in database |

### Output
Each violation prints to stderr in the form:
```
WARNING: task #42 "Apply block: router bgp 64610" references route-map TPX-INGRESS-IN (defined later in task #78)
```
Summary line at the end: `Dependency check: N warnings.`

### Exit behavior
Warnings only. `--strict` promotes warnings to exit code 1.

## 5. Validation — IP format and subnet membership

Runs during parsing, before `build_playbook`. Uses Python's stdlib `ipaddress` module.

### Prerequisite parser change
`parse_blocks` must track the source line number of every block header and every child. Warnings reference source-file line numbers.

### Syntactic checks (always applied)

| Context | Validation |
|---|---|
| Interface `ip address X Y [secondary]` | X valid IPv4, Y valid contiguous dotted-decimal mask |
| `ip dhcp pool … / network X Y` | X, Y valid; X equals network address of X/Y (no host bits set) |
| `ip dhcp pool … / default-router X` | valid IPv4; a host address (not network, not broadcast) |
| `ip dhcp pool … / dns-server X Y …` | each token valid IPv4 |
| `ip dhcp pool … / host X Y` | valid IPv4 + valid mask |
| `ip dhcp excluded-address A [B]` | valid IPv4s; A ≤ B when both present |
| `ip name-server X Y …` | each token valid IPv4 |
| `ntp server X` | valid IPv4 if X parses as an address; skip if hostname |
| `logging host X` | valid IPv4 if X parses as an address; skip if hostname |
| `radius server … / address ipv4 X …` | valid IPv4 |
| `router bgp … / bgp router-id X` | valid IPv4 |
| `router bgp … / neighbor X …` | valid IPv4 |
| `flow exporter … / destination X` | valid IPv4 |

Malformed IPv4 on a required field is an **error** (exit code 2, YAML not written) regardless of `--strict`. Mask-contiguity failures and host-bits-set failures are warnings by default; `--strict` promotes them.

### Same-block subnet-membership checks (hard checks)

| Block | Rule |
|---|---|
| `ip dhcp pool … / network X Y` + `default-router Z` | Z ∈ X/Y, Z ≠ network addr, Z ≠ broadcast addr |
| `ip dhcp pool … / network X Y` + `host A B` | A ∈ X/Y |
| Interface `ip address X Y` | X is a host in X/Y (not network, not broadcast) |

Warning by default, `--strict` promotes to exit 1.

### Across-block subnet-membership checks (soft, warning-only)

| Relationship | Rule |
|---|---|
| Interface VlanN ↔ DHCP pool network | If a pool's `network Z Y` matches a VlanN interface by subnet (not by name), masks must agree; if they don't, warn. |
| `ip dhcp excluded-address A [B]` | Both endpoints should be within at least one defined `ip dhcp pool … / network`. Warn if neither endpoint falls inside any pool network. |
| `router bgp … / neighbor X` | X should fall in the subnet of at least one interface IP (for directly-connected peering). Warn otherwise. |

These are never promoted by `--strict` — the false-positive rate is too high (eBGP-multihop, leases that intentionally sit outside any pool, etc.).

### Warning format
```
WARNING: line 540 (interface Vlan10 / ip address): 10.134.11.1 255.255.256.0 — invalid IPv4 mask
WARNING: line 73 (ip dhcp pool Management_VLAN / network): 10.134.1.113 has host bits set for /29 (network is 10.134.1.112)
WARNING: line 67 (ip dhcp pool Voice_VLAN / default-router): 10.134.11.129 is not in the pool subnet 10.134.11.128/25
```

### Implementation
After parsing but before `build_playbook`, construct two indexes:
- `dhcp_pool_networks`: `{pool_name: IPv4Network}` — sourced from `ip dhcp pool … / network` lines only.
- `interface_subnets`: `{iface_name: IPv4Interface}` — sourced from interface `ip address …` lines.

Validation functions query these indexes.

## 6. Firmware upgrade preamble (opt-in)

Emitted as Phase 0 when `--with-upgrade` is passed. Paranoid bundle mode. Fully Ansible-var-parameterized. The entire block (after the version-mismatch gate) is wrapped in `when: firmware_upgrade_needed` so re-running against an already-upgraded switch is a no-op.

### Required Ansible vars (user supplies at play-run time via `-e` or vars file)

| Var | Meaning |
|---|---|
| `firmware_image` | Image filename, e.g. `cat9k_iosxe.17.12.04.SPA.bin` |
| `firmware_md5` | Expected MD5 checksum of the image |
| `firmware_target_version` | Expected `ios_facts.ansible_net_version` after reload, e.g. `17.12.04` |

### Optional vars (with defaults)

| Var | Default | Meaning |
|---|---|---|
| `firmware_usb_device` | `usbflash0:` | Source device path |
| `firmware_flash_device` | `flash:` | Destination device |
| `firmware_reload_countdown` | `5` | Minutes for `reload in N` (console-cancellable grace) |
| `firmware_reload_timeout` | `900` | Seconds to wait for the switch to come back |
| `firmware_audit_dir` | `./audit` | Local directory for pre/post `show version` captures |
| `firmware_image_size_bytes` | `1073741824` (1 GiB) | Declared image size; free-space check asserts `bytes_free ≥ firmware_image_size_bytes * 1.1`. When unset, defaults to 1 GiB as a conservative upper bound. |
| `firmware_delete_prior` | `false` | Whether to delete the old image after successful upgrade |

### Task sequence (15 tasks, all post-task-2 gated by `firmware_upgrade_needed`)

1. `cisco.ios.ios_facts` → register `preupgrade_facts`.
2. `set_fact: firmware_upgrade_needed: "{{ preupgrade_facts.ansible_net_version != firmware_target_version }}"`, plus a `debug` line.
3. Verify image present on USB: `ios_command: ['dir {{ firmware_usb_device }}']` + `assert`.
4. Verify free space on `flash:`: parse `dir {{ firmware_flash_device }}` output, `assert` bytes_free ≥ `firmware_image_size_bytes * 1.1`.
5. Capture pre-upgrade `show version` to `{{ firmware_audit_dir }}/{{ inventory_hostname }}-pre-<timestamp>.txt` via `delegate_to: localhost`.
6. Copy USB → flash: `ios_command` with `prompt`/`answer` pairs for destination-filename and overwrite prompts.
7. Verify MD5: `ios_command: ['verify /md5 {{ firmware_flash_device }}{{ firmware_image }} {{ firmware_md5 }}']` + `assert Verified`.
8. Set boot variable: `cisco.ios.ios_config: lines: ['no boot system', 'boot system flash:{{ firmware_image }}']`, `save_when: modified`.
9. Save running-config: `ios_command: ['write memory']`.
10. `set_fact: firmware_prior_image: "{{ preupgrade_facts.ansible_net_image | basename }}"`.
11. Schedule reload: `ios_command: ['reload in {{ firmware_reload_countdown }}']` with prompt/answer for `[confirm]`.
12. `pause: seconds={{ firmware_reload_countdown * 60 + 30 }}` to let reload begin.
13. `ansible.builtin.wait_for_connection: delay=60 timeout={{ firmware_reload_timeout }}`.
14. `ios_facts` → `postupgrade_facts`, `assert: ansible_net_version == firmware_target_version`. Failure here aborts the play before any config tasks run.
15. Capture post-upgrade `show version` to audit dir; optionally `delete /force /recursive` the prior image when `firmware_delete_prior | bool`.

### Why same play, not a separate play
A single play means a single pass/fail report and facts gathered in Phase 0 remain available. A failed version assert aborts the play and config tasks don't run — which is exactly the desired behavior.

## 7. CLI surface

### New flags

| Flag | Behavior |
|---|---|
| `--with-upgrade` | Emit Phase 0 firmware preamble. No firmware values on the CLI — they are Ansible vars at play-run time. |
| `--strict` | Any dependency warning or same-block subnet-membership warning → exit code 1. YAML still written so it can be inspected. Across-block warnings never promote. |
| `--no-validate` | Skip all of Section 4 + 5 validation. Default: validation runs. |

### Existing flags (unchanged)
- `input` (positional), `-o/--output`, `--host`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | YAML written; validation clean or warnings only (non-strict) |
| 1 | YAML written; `--strict` is set and validation produced warnings |
| 2 | YAML NOT written; hard error (malformed IPv4 on required field, unparseable input, I/O error) |

### Stderr summary (unless `--no-validate`)
```
Parsed 97 blocks, 56 interfaces, 8 VLANs, 11 DHCP pools from FRS-QRS-SW01-2026-04-14.txt
Dependency check: 0 warnings
IP format check: 0 errors, 0 warnings
Subnet membership check: 0 warnings
Wrote FRS-QRS-SW01-2026-04-14.yml (1268 lines, 113 tasks)
```

### Usage examples
```bash
# Basic
python cisco_to_ansible.py FRS-QRS-SW01-2026-04-14.txt

# With firmware preamble
python cisco_to_ansible.py FRS-QRS-SW01-2026-04-14.txt --with-upgrade

# Strict — fail on any warning
python cisco_to_ansible.py FRS-QRS-SW01-2026-04-14.txt --strict

# Custom target/output
python cisco_to_ansible.py FRS-QRS-SW01-2026-04-14.txt \
  --host access_switches -o playbooks/FRS-QRS-SW01.yml

# Running the generated playbook with firmware vars:
ansible-playbook -i inventory playbooks/FRS-QRS-SW01.yml \
  -e firmware_image=cat9k_iosxe.17.12.04.SPA.bin \
  -e firmware_md5=9c2f6e4a... \
  -e firmware_target_version=17.12.04
```

## 8. Testing strategy

- **Regression**: re-run the tool against `FRS-QRS-SW01-2026-04-14.txt` and diff the output against a known-good expected YAML. Commit the expected fixture.
- **Order invariants**: after generation, parse the YAML and walk tasks asserting (a) VRFs defined before any `vrf forwarding`, (b) flow monitors defined before any `ip flow monitor`, (c) ACLs before route-maps, (d) route-maps before BGP, (e) STP mode task index < any `enabled: true` interface task index.
- **Validation unit tests**: synthetic mini-configs that trigger each warning (malformed mask, host bits in network address, default-router outside pool, neighbor outside all interface subnets, flow monitor referenced before defined). Each must emit the expected warning text.
- **Firmware block**: not runnable without a real switch; sanity-check by (a) YAML-parsing the output, (b) asserting task names and ordering, (c) asserting `when: firmware_upgrade_needed` is applied to tasks 3–15.

## 9. Out-of-scope / later

- IPv6 validation.
- Install-mode firmware upgrade for modern Cat9k.
- Stack-aware upgrades.
- Structured emission of `router bgp` via `cisco.ios.ios_bgp_global` / `ios_bgp_address_family`. For now BGP stays raw.
- Structured emission of DHCP pools via a dedicated module. Cisco's `cisco.ios` collection has limited DHCP support; raw `ios_config` is the pragmatic choice.
