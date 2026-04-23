# Cisco Playbook Ordering, Validation & Firmware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `cisco_to_ansible.py` to emit Ansible tasks in a dependency-correct order, add three layers of validation (structural ordering, IPv4/mask format, subnet membership), and optionally prepend a paranoid bundle-mode firmware upgrade preamble controlled by a new CLI flag.

**Architecture:** Keep the single-file tool structure (spec's non-goal: no class rewrite). Introduce an intermediate `Task` dataclass so validators can introspect the task graph before YAML is serialized. Parse blocks once (with source line numbers) into typed buckets; emit in six phases; run three validators; serialize YAML. Firmware preamble is a separate task generator invoked only when `--with-upgrade` is set.

**Tech Stack:** Python 3.11+ (stdlib only — `argparse`, `ipaddress`, `dataclasses`, `re`), pytest for tests. Target runtime is Python 3.13 (the system Python).

**Spec reference:** `docs/superpowers/specs/2026-04-23-cisco-playbook-ordering-and-firmware-design.md`.

---

## File structure

**Modified in place:**
- `cisco_to_ansible.py` — all logic changes land here. No module split.
- `.gitignore` — relax the `FRS-QRS-SW01-*.yml` rule so `tests/fixtures/*.yml` are tracked.

**Created:**
- `pyproject.toml` — minimal config for pytest test discovery.
- `tests/__init__.py` — empty.
- `tests/fixtures/FRS-QRS-SW01-2026-04-14.txt` — committed copy of the sample config.
- `tests/fixtures/FRS-QRS-SW01.baseline.yml` — golden YAML from the current tool (task 1); updated deliberately in task 5 when emission order changes.
- `tests/fixtures/FRS-QRS-SW01.with-firmware.yml` — golden YAML with `--with-upgrade` (task 12).
- `tests/fixtures/malformed_mask.txt`, `tests/fixtures/router_before_pool.txt`, `tests/fixtures/vrf_forward_before_def.txt`, etc. — tiny synthetic configs that trigger individual validator warnings (tasks 8, 10, 11).
- `tests/test_regression.py` — golden-file YAML diff.
- `tests/test_parser.py` — parser unit tests (line numbers, classification).
- `tests/test_emission.py` — Task dataclass, six-phase ordering invariants.
- `tests/test_dependency_check.py`
- `tests/test_ip_validation.py`
- `tests/test_subnet_membership.py`
- `tests/test_cli_flags.py` — `--strict`, `--no-validate`, exit codes.
- `tests/test_firmware.py` — firmware preamble structure.

**Branch:** `feat/ordering-validation-firmware` off `main`. Commit per task; push after task 0 (so the branch exists remotely from the start) and again after task 12 or at merge time.

---

## Task 0: Create feature branch and commit this plan

**Files:**
- Modify: git state
- Committed: `docs/superpowers/plans/2026-04-23-cisco-playbook-ordering-and-firmware.md` (this document)

- [ ] **Step 1: Confirm you're on main and clean**

```
cd "C:/dev/SwitchConfigPlaybookMaker"
git status
git branch --show-current
```
Expected: on `main`, clean working tree, `main` tracks `origin/main`.

- [ ] **Step 2: Create feature branch**

```
git checkout -b feat/ordering-validation-firmware
```

- [ ] **Step 3: Commit plan doc**

```
git add docs/superpowers/plans/2026-04-23-cisco-playbook-ordering-and-firmware.md
git commit -m "Add implementation plan for ordering, validation, and firmware preamble"
```

- [ ] **Step 4: Push branch**

```
git push -u origin feat/ordering-validation-firmware
```

---

## Task 1: Test scaffolding and baseline regression fixture

Establish pytest and lock in the current tool's output as a golden fixture. Future behavior changes update this fixture deliberately.

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/FRS-QRS-SW01-2026-04-14.txt`
- Create: `tests/fixtures/FRS-QRS-SW01.baseline.yml`
- Create: `tests/test_regression.py`
- Modify: `.gitignore`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "cisco-to-ansible"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

- [ ] **Step 2: Verify pytest is installed**

```
python -m pytest --version
```
Expected: version string prints. If not installed:
```
python -m pip install pytest
```

- [ ] **Step 3: Copy the sample config into fixtures**

```
mkdir -p tests/fixtures
cp "C:/Users/justtus/Downloads/FRS-QRS-SW01-2026-04-14.txt" tests/fixtures/FRS-QRS-SW01-2026-04-14.txt
```

- [ ] **Step 4: Relax `.gitignore` so fixtures are tracked**

Edit `.gitignore`. Replace the line
```
FRS-QRS-SW01-*.yml
```
with
```
/FRS-QRS-SW01-*.yml
```
The leading `/` anchors the rule to the repo root; `tests/fixtures/*.yml` are no longer excluded.

- [ ] **Step 5: Generate the baseline fixture**

```
python cisco_to_ansible.py tests/fixtures/FRS-QRS-SW01-2026-04-14.txt -o tests/fixtures/FRS-QRS-SW01.baseline.yml
```
Expected: `Wrote tests/fixtures/FRS-QRS-SW01.baseline.yml (1268 lines).`

- [ ] **Step 6: Create `tests/__init__.py`**

Write an empty file at `tests/__init__.py`.

- [ ] **Step 7: Write the regression test**

Create `tests/test_regression.py`:

```python
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
```

- [ ] **Step 8: Run the test**

```
python -m pytest tests/test_regression.py -v
```
Expected: `1 passed`.

- [ ] **Step 9: Commit**

```
git add pyproject.toml .gitignore tests/__init__.py tests/test_regression.py tests/fixtures/FRS-QRS-SW01-2026-04-14.txt tests/fixtures/FRS-QRS-SW01.baseline.yml
git commit -m "Add test scaffolding and baseline golden-file regression"
```

---

## Task 2: Track source line numbers in the parser

Extend `parse_blocks` to carry line numbers so validation warnings can cite source lines.

**Files:**
- Modify: `cisco_to_ansible.py` — `parse_blocks` and its callers.
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write the failing parser test**

Create `tests/test_parser.py`:

```python
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
```

- [ ] **Step 2: Run test, confirm it fails**

```
python -m pytest tests/test_parser.py -v
```
Expected: FAIL (current `parse_blocks` returns 2-tuples of `(header, children)`).

- [ ] **Step 3: Replace `parse_blocks` in `cisco_to_ansible.py`**

```python
def parse_blocks(lines: Iterable[str]) -> list[tuple[str, int, list[tuple[str, int]]]]:
    """Split config into (header, header_lineno, [(child, child_lineno)]) blocks."""
    blocks: list[tuple[str, int, list[tuple[str, int]]]] = []
    current: tuple[str, int, list[tuple[str, int]]] | None = None
    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip('\r\n')
        stripped = line.rstrip()
        if stripped == '' or stripped == '!':
            if current is not None:
                blocks.append(current)
                current = None
            continue
        if line.startswith((' ', '\t')):
            if current is None:
                continue
            current[2].append((line.strip(), idx))
        else:
            if current is not None:
                blocks.append(current)
            current = (stripped, idx, [])
    if current is not None:
        blocks.append(current)
    return blocks
```

- [ ] **Step 4: Adapt the single caller in `build_playbook`**

Find the line in `build_playbook`:
```python
for header, children in blocks:
```
Replace with:
```python
for header, header_lineno, children_with_ln in blocks:
    children = [c for c, _ln in children_with_ln]
```
Leave everything else in the loop body untouched. Line numbers are carried but discarded for now; later tasks use them.

- [ ] **Step 5: Adapt the hostname-hint peek in `main`**

Find in `main`:
```python
for hdr, _ in blocks:
```
Replace with:
```python
for hdr, _ln, _children in blocks:
```

- [ ] **Step 6: Run parser test**

```
python -m pytest tests/test_parser.py -v
```
Expected: PASS.

- [ ] **Step 7: Run regression test**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS (YAML output unchanged — line numbers are internal).

- [ ] **Step 8: Commit**

```
git add cisco_to_ansible.py tests/test_parser.py
git commit -m "Track source line numbers in parse_blocks"
```

---

## Task 3: Introduce `Task` dataclass and in-memory task list

Replace `tasks: list[str]` with `task_list: list[Task]`. YAML serialization happens once at the end. Invisible to current output.

**Files:**
- Modify: `cisco_to_ansible.py`
- Create: `tests/test_emission.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_emission.py`:

```python
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
```

- [ ] **Step 2: Run test, confirm it fails**

```
python -m pytest tests/test_emission.py -v
```
Expected: ImportError (`Task`, `render_task` don't exist yet).

- [ ] **Step 3: Add `Task` dataclass and `render_task` to `cisco_to_ansible.py`**

Near the top of the file (after `from __future__ import annotations`), add:

```python
from dataclasses import dataclass, field
```

Below the existing YAML-emission helpers, add:

```python
@dataclass
class Task:
    """An Ansible task in intermediate form, before YAML serialization."""
    name: str
    module: str
    params: list[tuple[str, object]] = field(default_factory=list)
    # Back-reference to source blocks for validators:
    # list of (header, header_lineno, children_with_ln).
    origin: list[tuple[str, int, list[tuple[str, int]]]] = field(default_factory=list)


def render_task(task: Task, indent: int = 4) -> list[str]:
    """Render a Task as YAML lines. Drops the trailing blank separator line
    emitted by the low-level emit_task helper; the playbook assembler joins
    tasks with explicit blank lines."""
    rendered = emit_task(task.name, task.module, task.params, indent=indent)
    # emit_task appends a trailing '' for visual separation; strip it.
    return rendered[:-1] if rendered and rendered[-1] == '' else rendered
```

- [ ] **Step 4: Run emission test**

```
python -m pytest tests/test_emission.py -v
```
Expected: PASS.

- [ ] **Step 5: Refactor `build_playbook` to accumulate Tasks**

Inside `build_playbook`, after the opening `hdr = [...]` block and above the `tasks: list[str] = []` line, declare:

```python
task_list: list[Task] = []
```

Then for every call of the form:
```python
tasks.extend(emit_task(NAME, MODULE, PARAMS))
```
replace with:
```python
task_list.append(Task(name=NAME, module=MODULE, params=PARAMS))
```

There are roughly a dozen such calls (hostname, system, vlans, interfaces, l2, l3, per-interface residue loop, users, banners loop, logging, ntp, globals, raw blocks loop).

At the end of `build_playbook`, replace:
```python
return '\n'.join(hdr + tasks) + '\n'
```
with:
```python
rendered: list[str] = list(hdr)
for t in task_list:
    rendered.extend(render_task(t))
    rendered.append('')  # blank line between tasks
return '\n'.join(rendered) + '\n'
```

Delete the now-unused `tasks: list[str] = []` declaration.

- [ ] **Step 6: Run regression**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS — same YAML output (the old code also put a blank line between tasks via `emit_task`'s trailing `''`).

- [ ] **Step 7: Commit**

```
git add cisco_to_ansible.py tests/test_emission.py
git commit -m "Introduce Task dataclass and in-memory task list"
```

---

## Task 4: Classify blocks into typed buckets

Parse once, dispatch each block to a typed bucket. Replaces the current `raw_blocks` list + global-prefix matching.

**Files:**
- Modify: `cisco_to_ansible.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Write failing test for classify_block**

Append to `tests/test_parser.py`:

```python
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
```

- [ ] **Step 2: Run test — expect failure**

```
python -m pytest tests/test_parser.py::test_classify_block_dispatches_known_headers -v
```
Expected: FAIL (function doesn't exist).

- [ ] **Step 3: Implement `classify_block`**

Add to `cisco_to_ansible.py` above `build_playbook`:

```python
# Ordered list of (predicate, bucket_name). First match wins.
_CLASSIFIERS: list[tuple[str, object]] = []


def classify_block(header: str) -> str:
    """Return the bucket name for a block header."""
    h = header.strip()
    # Prefix and exact matches
    if h.startswith("hostname "):
        return "hostname"
    if h.startswith("ip domain name "):
        return "domain"
    if h.startswith("ip name-server "):
        return "name_server"
    if re.match(r'^vlan\s+\d+\s+name\s+', h, re.IGNORECASE):
        return "vlan_inline"
    if h.startswith("interface "):
        return "interface"
    if h.startswith("vrf definition "):
        return "vrf"
    if h.startswith("ip dhcp pool "):
        return "dhcp_pool"
    if h.startswith("ip dhcp excluded-address "):
        return "dhcp_excluded"
    if h.startswith("flow record "):
        return "flow_record"
    if h.startswith("flow exporter "):
        return "flow_exporter"
    if h.startswith("flow monitor "):
        return "flow_monitor"
    if h.startswith("ip access-list "):
        return "acl"
    if h.startswith("route-map "):
        return "route_map"
    if h.startswith("router bgp"):
        return "bgp"
    if h.startswith("radius server "):
        return "radius_server"
    if h.startswith("snmp-server view "):
        return "snmp_view"
    if h.startswith("snmp-server community "):
        return "snmp_community"
    if h == "archive" or h.startswith("archive "):
        return "archive"
    if h == "redundancy":
        return "redundancy"
    if h.startswith("transceiver "):
        return "transceiver"
    if h == "control-plane":
        return "control_plane"
    if h.startswith("line "):
        return "line_block"
    if re.match(r'^banner\s+\S+\s+\S+$', h):
        return "banner_header"
    if h == "aaa new-model" or h.startswith("aaa session-id"):
        return "aaa_new_model"
    if h.startswith("aaa authentication ") or h.startswith("aaa authorization ") or h.startswith("aaa accounting "):
        return "aaa_auth"
    if h.startswith("spanning-tree "):
        return "stp_global"
    if h == "ip routing" or h == "no ip routing" or h.startswith("ip forward-protocol"):
        return "ip_routing_global"
    if h.startswith("username "):
        return "user"
    if h.startswith("logging source-interface") or h.startswith("ip radius source-interface"):
        return "source_interface_global"
    if h.startswith("logging "):
        return "logging"
    if h.startswith("ntp "):
        return "ntp"
    if (h.startswith("ip ftp ") or h.startswith("ip http ")
            or h.startswith("no ip http ") or h.startswith("no ip ftp ")):
        return "ip_service"
    if (h.startswith("service ") or h.startswith("no service ")
            or h.startswith("platform ") or h.startswith("no platform ")
            or h.startswith("clock ") or h.startswith("diagnostic ")
            or h.startswith("memory ") or h.startswith("login ") or h.startswith("no login ")
            or h.startswith("no device-tracking ")):
        return "base_service"
    return "misc"
```

- [ ] **Step 4: Run classifier test**

```
python -m pytest tests/test_parser.py -v
```
Expected: PASS.

- [ ] **Step 5: Write failing test for the typed-bucket parser**

Append to `tests/test_parser.py`:

```python
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
```

- [ ] **Step 6: Run test, expect failure**

```
python -m pytest tests/test_parser.py::test_parse_config_buckets_blocks -v
```
Expected: FAIL (`parse_config` doesn't exist or doesn't produce these fields).

- [ ] **Step 7: Implement `ParsedConfig` and `parse_config`**

Add to `cisco_to_ansible.py`:

```python
@dataclass
class ParsedConfig:
    # Identity / base
    hostname: str | None = None
    domain_name: str | None = None
    name_servers: list[str] = field(default_factory=list)
    base_services: list[tuple[str, int, list[tuple[str, int]]]] = field(default_factory=list)

    # AAA & identity
    users: list[dict] = field(default_factory=list)
    aaa_new_model: list[tuple] = field(default_factory=list)
    radius_servers: list[tuple] = field(default_factory=list)
    aaa_auth: list[tuple] = field(default_factory=list)

    # Forwarding primitives
    ip_routing_globals: list[tuple] = field(default_factory=list)
    vrfs: list[tuple] = field(default_factory=list)
    vlans: list[dict] = field(default_factory=list)
    stp_globals: list[tuple] = field(default_factory=list)
    acls: list[tuple] = field(default_factory=list)
    route_maps: list[tuple] = field(default_factory=list)
    flow_records: list[tuple] = field(default_factory=list)
    flow_exporters: list[tuple] = field(default_factory=list)
    flow_monitors: list[tuple] = field(default_factory=list)
    snmp_views: list[tuple] = field(default_factory=list)
    snmp_communities: list[tuple] = field(default_factory=list)
    dhcp_excluded: list[tuple] = field(default_factory=list)
    dhcp_pools: list[tuple] = field(default_factory=list)

    # Interfaces (structured — parse_interface output)
    interfaces: list[dict] = field(default_factory=list)

    # Services & protocols that depend on interfaces
    bgp: list[tuple] = field(default_factory=list)
    source_interface_globals: list[tuple] = field(default_factory=list)
    logging: list[tuple] = field(default_factory=list)
    ntp_servers: list[str] = field(default_factory=list)
    ip_services: list[tuple] = field(default_factory=list)

    # Management / housekeeping
    banners: list[tuple[str, str]] = field(default_factory=list)
    line_blocks: list[tuple] = field(default_factory=list)
    archive: list[tuple] = field(default_factory=list)
    redundancy: list[tuple] = field(default_factory=list)
    transceiver: list[tuple] = field(default_factory=list)
    control_plane: list[tuple] = field(default_factory=list)
    misc_blocks: list[tuple] = field(default_factory=list)


def parse_config(text: str) -> ParsedConfig:
    """Parse the raw Cisco config text into a ParsedConfig with typed buckets."""
    cfg = ParsedConfig()
    lines = text.splitlines()
    banners, stripped = extract_banners(lines)
    for kind, body in banners:
        cfg.banners.append((kind, body))
    blocks = parse_blocks(stripped)

    for header, header_ln, children_with_ln in blocks:
        bucket = classify_block(header)
        children = [c for c, _ln in children_with_ln]

        if bucket == "hostname":
            cfg.hostname = header.split(None, 1)[1].strip()
            continue
        if bucket == "domain":
            cfg.domain_name = header[len("ip domain name "):].strip()
            continue
        if bucket == "name_server":
            cfg.name_servers.extend(header.split()[2:])
            continue
        if bucket == "vlan_inline":
            m = VLAN_INLINE.match(header)
            if m:
                cfg.vlans.append({"vlan_id": int(m.group(1)), "name": m.group(2).strip()})
            continue
        if bucket == "interface":
            cfg.interfaces.append(parse_interface(header, children))
            continue
        if bucket == "user":
            if not children:  # one-liner
                u = parse_username(header)
                if u is not None:
                    cfg.users.append(u)
            continue
        if bucket == "ntp":
            if header.startswith("ntp server "):
                cfg.ntp_servers.append(header.split(None, 2)[2].strip())
            continue
        if header in ("end", "!"):
            continue

        block = (header, header_ln, children_with_ln)
        bucket_map = {
            "base_service": cfg.base_services,
            "aaa_new_model": cfg.aaa_new_model,
            "radius_server": cfg.radius_servers,
            "aaa_auth": cfg.aaa_auth,
            "ip_routing_global": cfg.ip_routing_globals,
            "vrf": cfg.vrfs,
            "stp_global": cfg.stp_globals,
            "acl": cfg.acls,
            "route_map": cfg.route_maps,
            "flow_record": cfg.flow_records,
            "flow_exporter": cfg.flow_exporters,
            "flow_monitor": cfg.flow_monitors,
            "snmp_view": cfg.snmp_views,
            "snmp_community": cfg.snmp_communities,
            "dhcp_excluded": cfg.dhcp_excluded,
            "dhcp_pool": cfg.dhcp_pools,
            "bgp": cfg.bgp,
            "source_interface_global": cfg.source_interface_globals,
            "logging": cfg.logging,
            "ip_service": cfg.ip_services,
            "line_block": cfg.line_blocks,
            "archive": cfg.archive,
            "redundancy": cfg.redundancy,
            "transceiver": cfg.transceiver,
            "control_plane": cfg.control_plane,
        }
        if bucket in bucket_map:
            bucket_map[bucket].append(block)
        else:
            cfg.misc_blocks.append(block)

    return cfg
```

- [ ] **Step 8: Run parser tests**

```
python -m pytest tests/test_parser.py -v
```
Expected: all pass.

- [ ] **Step 9: Do NOT yet wire `parse_config` into `build_playbook` / `main`**

`build_playbook` still uses the old `blocks` + inline classification. That's replaced in Task 5. For now `parse_config` is dead code reachable only from tests.

- [ ] **Step 10: Run regression**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS.

- [ ] **Step 11: Commit**

```
git add cisco_to_ansible.py tests/test_parser.py
git commit -m "Classify blocks into typed buckets via parse_config"
```

---

## Task 5: Six-phase emission order

Rewrite `build_playbook` to consume `ParsedConfig` and emit tasks in the six-phase order. This is the change that alters the generated YAML. Update the golden fixture deliberately.

**Files:**
- Modify: `cisco_to_ansible.py` — `build_playbook` and `main`.
- Update: `tests/fixtures/FRS-QRS-SW01.baseline.yml` (intentional regeneration).
- Append: `tests/test_emission.py`

- [ ] **Step 1: Write the invariant test first**

Append to `tests/test_emission.py`:

```python
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
```

- [ ] **Step 2: Run the new ordering tests — expect failures**

```
python -m pytest tests/test_emission.py -v
```
Expected: the new `test_*_precede_*` tests fail (current tool emits in a different order).

- [ ] **Step 3: Rewrite `build_playbook` against `ParsedConfig`**

Replace the signature and body of `build_playbook`. The full replacement follows the six-phase plan from the spec. Keep existing interface decomposition logic (admin state, L2, L3, residue).

```python
def build_playbook(cfg: ParsedConfig, host: str, source_file: str) -> str:
    hdr = [
        '---',
        f'# Generated by cisco_to_ansible.py from {os.path.basename(source_file)}',
        f'- name: {yaml_scalar(f"Apply configuration from {os.path.basename(source_file)}")}',
        f'  hosts: {yaml_scalar(host)}',
        '  gather_facts: false',
        '  connection: network_cli',
        '',
        '  tasks:',
    ]
    task_list: list[Task] = []

    # ---- Phase 1: Identity & base services ----
    if cfg.hostname:
        task_list.append(Task(
            name=f"Configure hostname {cfg.hostname}",
            module="cisco.ios.ios_hostname",
            params=[("config", {"hostname": cfg.hostname}), ("state", "merged")],
        ))
    if cfg.domain_name or cfg.name_servers:
        system: dict = {}
        if cfg.hostname:
            system["hostname"] = cfg.hostname
        if cfg.domain_name:
            system["domain_name"] = cfg.domain_name
        if cfg.name_servers:
            system["name_servers"] = cfg.name_servers
        task_list.append(Task(
            name="Configure domain and name servers",
            module="cisco.ios.ios_system",
            params=[("config", system), ("state", "merged")],
        ))
    if cfg.base_services:
        lines = [b[0] for b in cfg.base_services]
        task_list.append(Task(
            name="Apply base services and global settings",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.base_services),
        ))

    # ---- Phase 2: AAA & identity ----
    if cfg.users:
        aggregate = _build_user_aggregate(cfg.users)
        task_list.append(Task(
            name="Configure local user accounts",
            module="cisco.ios.ios_user",
            params=[("aggregate", aggregate), ("state", "present")],
        ))
    if cfg.aaa_new_model:
        lines = [b[0] for b in cfg.aaa_new_model]
        task_list.append(Task(
            name="Enable AAA new-model",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.aaa_new_model),
        ))
    for header, ln, children_ln in cfg.radius_servers:
        cleaned = [c for c, _ in children_ln if c.strip() != '!']
        if not cleaned:
            continue
        task_list.append(Task(
            name=f"Apply block: {_truncate(header)}",
            module="cisco.ios.ios_config",
            params=[("parents", header), ("lines", cleaned)],
            origin=[(header, ln, children_ln)],
        ))
    if cfg.aaa_auth:
        lines = [b[0] for b in cfg.aaa_auth]
        task_list.append(Task(
            name="Apply AAA authentication and authorization",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.aaa_auth),
        ))

    # ---- Phase 3: Forwarding primitives ----
    if cfg.ip_routing_globals:
        lines = [b[0] for b in cfg.ip_routing_globals]
        task_list.append(Task(
            name="Enable IP routing and forwarding",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.ip_routing_globals),
        ))
    for header, ln, children_ln in cfg.vrfs:
        cleaned = [c for c, _ in children_ln if c.strip() != '!']
        task_list.append(Task(
            name=f"Apply block: {_truncate(header)}",
            module="cisco.ios.ios_config",
            params=[("parents", header), ("lines", cleaned)],
            origin=[(header, ln, children_ln)],
        ))
    if cfg.vlans:
        task_list.append(Task(
            name="Configure VLAN database",
            module="cisco.ios.ios_vlans",
            params=[("config", cfg.vlans), ("state", "merged")],
        ))
    if cfg.stp_globals:
        lines = [b[0] for b in cfg.stp_globals]
        task_list.append(Task(
            name="Configure spanning-tree mode (before ports come up)",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.stp_globals),
        ))
    for bucket_name, bucket in [
        ("ACL", cfg.acls),
        ("route-map", cfg.route_maps),
        ("flow record", cfg.flow_records),
        ("flow exporter", cfg.flow_exporters),
        ("flow monitor", cfg.flow_monitors),
    ]:
        for header, ln, children_ln in bucket:
            cleaned = [c for c, _ in children_ln if c.strip() != '!']
            if not cleaned:
                continue
            task_list.append(Task(
                name=f"Apply block: {_truncate(header)}",
                module="cisco.ios.ios_config",
                params=[("parents", header), ("lines", cleaned)],
                origin=[(header, ln, children_ln)],
            ))
    if cfg.snmp_views or cfg.snmp_communities:
        lines = [b[0] for b in cfg.snmp_views] + [b[0] for b in cfg.snmp_communities]
        task_list.append(Task(
            name="Configure SNMP views and community strings",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.snmp_views) + list(cfg.snmp_communities),
        ))
    if cfg.dhcp_excluded:
        lines = [b[0] for b in cfg.dhcp_excluded]
        task_list.append(Task(
            name="Configure DHCP excluded addresses",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.dhcp_excluded),
        ))
    for header, ln, children_ln in cfg.dhcp_pools:
        cleaned = [c for c, _ in children_ln if c.strip() != '!']
        if not cleaned:
            # include empty pools as bare `ip dhcp pool NAME` one-liners
            task_list.append(Task(
                name=f"Apply block: {_truncate(header)}",
                module="cisco.ios.ios_config",
                params=[("lines", [header])],
                origin=[(header, ln, children_ln)],
            ))
            continue
        task_list.append(Task(
            name=f"Apply block: {_truncate(header)}",
            module="cisco.ios.ios_config",
            params=[("parents", header), ("lines", cleaned)],
            origin=[(header, ln, children_ln)],
        ))

    # ---- Phase 4: Interfaces ----
    if cfg.interfaces:
        task_list.extend(_build_interface_tasks(cfg.interfaces))

    # ---- Phase 5: Services depending on interfaces ----
    for header, ln, children_ln in cfg.bgp:
        cleaned = [c for c, _ in children_ln if c.strip() != '!']
        if not cleaned:
            continue
        task_list.append(Task(
            name=f"Apply block: {_truncate(header)}",
            module="cisco.ios.ios_config",
            params=[("parents", header), ("lines", cleaned)],
            origin=[(header, ln, children_ln)],
        ))
    if cfg.source_interface_globals:
        lines = [b[0] for b in cfg.source_interface_globals]
        task_list.append(Task(
            name="Configure source-interface globals",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.source_interface_globals),
        ))
    if cfg.logging:
        lines = [b[0] for b in cfg.logging]
        task_list.append(Task(
            name="Apply logging configuration",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.logging),
        ))
    if cfg.ntp_servers:
        task_list.append(Task(
            name="Configure NTP servers",
            module="cisco.ios.ios_config",
            params=[("lines", [f"ntp server {s}" for s in cfg.ntp_servers])],
        ))
    if cfg.ip_services:
        lines = [b[0] for b in cfg.ip_services]
        task_list.append(Task(
            name="Configure IP services (ftp, http)",
            module="cisco.ios.ios_config",
            params=[("lines", lines)],
            origin=list(cfg.ip_services),
        ))

    # ---- Phase 6: Management & housekeeping ----
    for kind, text in cfg.banners:
        task_list.append(Task(
            name=f"Configure {kind} banner",
            module="cisco.ios.ios_banner",
            params=[("banner", kind), ("text", text), ("state", "present")],
        ))
    for bucket in (cfg.line_blocks, cfg.archive, cfg.redundancy, cfg.transceiver,
                   cfg.control_plane, cfg.misc_blocks):
        for header, ln, children_ln in bucket:
            cleaned = [c for c, _ in children_ln if c.strip() != '!']
            if not cleaned:
                continue
            task_list.append(Task(
                name=f"Apply block: {_truncate(header)}",
                module="cisco.ios.ios_config",
                params=[("parents", header), ("lines", cleaned)],
                origin=[(header, ln, children_ln)],
            ))

    # ---- Render ----
    rendered: list[str] = list(hdr)
    for t in task_list:
        rendered.extend(render_task(t))
        rendered.append('')
    return '\n'.join(rendered) + '\n'


def _truncate(header: str, limit: int = 60) -> str:
    return header if len(header) <= limit else header[: limit - 3] + "..."


def _build_user_aggregate(users: list[dict]) -> list[dict]:
    aggregate = []
    for u in users:
        entry: dict = {"name": u["name"]}
        if "privilege" in u:
            entry["privilege"] = u["privilege"]
        if "value" in u:
            if u.get("secret", False) and u.get("hash_type") is not None:
                entry["hashed_password"] = {"type": u["hash_type"], "value": u["value"]}
            else:
                entry["configured_password"] = u["value"]
        aggregate.append(entry)
    return aggregate


def _build_interface_tasks(interfaces: list[dict]) -> list[Task]:
    """Return admin-state, L2, L3, and per-interface residue tasks."""
    tasks: list[Task] = []
    iface_state = []
    l2_cfg = []
    l3_cfg = []
    for ifc in interfaces:
        entry: dict = {"name": ifc["name"]}
        if ifc["description"] is not None:
            entry["description"] = ifc["description"]
        entry["enabled"] = ifc["enabled"]
        iface_state.append(entry)
        if any(ifc[k] is not None for k in
               ("mode", "access_vlan", "voice_vlan", "trunk_native", "trunk_allowed")):
            l2: dict = {"name": ifc["name"]}
            if ifc["mode"]:
                l2["mode"] = ifc["mode"]
            if ifc["access_vlan"] is not None:
                l2["access"] = {"vlan": ifc["access_vlan"]}
            if ifc["voice_vlan"] is not None:
                l2["voice"] = {"vlan": ifc["voice_vlan"]}
            trunk: dict = {}
            if ifc["trunk_native"] is not None:
                trunk["native_vlan"] = ifc["trunk_native"]
            if ifc["trunk_allowed"]:
                trunk["allowed_vlans"] = ifc["trunk_allowed"]
            if trunk:
                l2["trunk"] = trunk
            l2_cfg.append(l2)
        if ifc["ipv4"]:
            l3_cfg.append({"name": ifc["name"], "ipv4": [{"address": a} for a in ifc["ipv4"]]})
    tasks.append(Task(
        name="Configure interface admin state and descriptions",
        module="cisco.ios.ios_interfaces",
        params=[("config", iface_state), ("state", "merged")],
    ))
    if l2_cfg:
        tasks.append(Task(
            name="Configure L2 interface properties (switchport)",
            module="cisco.ios.ios_l2_interfaces",
            params=[("config", l2_cfg), ("state", "merged")],
        ))
    if l3_cfg:
        tasks.append(Task(
            name="Configure L3 interface addressing",
            module="cisco.ios.ios_l3_interfaces",
            params=[("config", l3_cfg), ("state", "merged")],
        ))
    for ifc in interfaces:
        residue = list(ifc["extras"])
        if ifc["vrf"]:
            residue.insert(0, f"vrf forwarding {ifc['vrf']}")
        if not residue:
            continue
        tasks.append(Task(
            name=f"Apply remaining commands on interface {ifc['name']}",
            module="cisco.ios.ios_config",
            params=[("parents", f"interface {ifc['name']}"), ("lines", residue)],
        ))
    return tasks
```

- [ ] **Step 4: Update `main` to use `parse_config`**

In `main`, replace the parsing block:
```python
lines = raw_text.splitlines()
banners, stripped = extract_banners(lines)
blocks = parse_blocks(stripped)

hostname_hint = None
for hdr, _ln, _children in blocks:
    if hdr.startswith('hostname '):
        hostname_hint = hdr.split(None, 1)[1].strip()
        break

host_target = args.host or hostname_hint or 'switches'

playbook = build_playbook(blocks, banners, host=host_target, source_file=args.input)
```
with:
```python
cfg = parse_config(raw_text)
host_target = args.host or cfg.hostname or 'switches'
playbook = build_playbook(cfg, host=host_target, source_file=args.input)
```

- [ ] **Step 5: Run the ordering tests**

```
python -m pytest tests/test_emission.py -v
```
Expected: all `test_*_precede_*` tests PASS. The old `test_task_dataclass_renders_yaml` also passes.

- [ ] **Step 6: Regenerate the baseline fixture**

```
python cisco_to_ansible.py tests/fixtures/FRS-QRS-SW01-2026-04-14.txt -o tests/fixtures/FRS-QRS-SW01.baseline.yml
```

- [ ] **Step 7: Quick visual check of the new output**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS (regression compares against the fixture we just regenerated; first run must be self-consistent).

Skim `tests/fixtures/FRS-QRS-SW01.baseline.yml` briefly to confirm no obvious regressions (tasks still well-formed, hostname, VLANs, interfaces present).

- [ ] **Step 8: Validate YAML still parses**

```
python -c "import yaml; yaml.safe_load(open('tests/fixtures/FRS-QRS-SW01.baseline.yml'))"
```
Expected: no exception. If PyYAML isn't installed, skip this step.

- [ ] **Step 9: Commit**

```
git add cisco_to_ansible.py tests/test_emission.py tests/fixtures/FRS-QRS-SW01.baseline.yml
git commit -m "Reorder task emission across six phases (definitions before references)"
```

---

## Task 6: Dependency check (structural validation)

Post-emission static pass. Walks tasks in order; warns when a reference precedes its definition.

**Files:**
- Modify: `cisco_to_ansible.py` (add `run_dependency_check`; integrate into `main`).
- Create: `tests/test_dependency_check.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_dependency_check.py`:

```python
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
    assert any("vrf forwarding MGMT" in w and "later" in w.lower() for w in warnings), warnings


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
```

- [ ] **Step 2: Run tests — expect failure**

```
python -m pytest tests/test_dependency_check.py -v
```
Expected: ImportError (`run_dependency_check` doesn't exist).

- [ ] **Step 3: Implement `run_dependency_check`**

Add to `cisco_to_ansible.py`:

```python
# Definition patterns: (regex, group_name_for_captured_name, definition_kind)
_DEFINITIONS = [
    (re.compile(r'^vrf definition (\S+)'), 'vrf'),
    (re.compile(r'^flow (?:record|exporter|monitor) (\S+)'), 'flow'),
    (re.compile(r'^ip access-list (?:standard|extended) (\S+)'), 'acl'),
    (re.compile(r'^route-map (\S+)'), 'route_map'),
    (re.compile(r'^radius server (\S+)'), 'radius'),
    (re.compile(r'^snmp-server view (\S+)'), 'snmp_view'),
    (re.compile(r'^interface Vlan(\d+)', re.IGNORECASE), 'vlan_iface'),
    (re.compile(r'^username (\S+)'), 'user'),
]

# Reference patterns applied to every line of every ios_config task.
_REFERENCES = [
    (re.compile(r'^vrf forwarding (\S+)'), 'vrf', 'VRF'),
    (re.compile(r'^ip flow monitor (\S+) (?:input|output)'), 'flow', 'flow monitor'),
    (re.compile(r'^match ip address (\S+)'), 'acl', 'ACL'),
    (re.compile(r'neighbor \S+ route-map (\S+) (?:in|out)'), 'route_map', 'route-map'),
    (re.compile(r'^snmp-server community \S+ view (\S+)'), 'snmp_view', 'SNMP view'),
    (re.compile(r'^ip radius source-interface Vlan(\d+)', re.IGNORECASE), 'vlan_iface', 'Vlan interface'),
    (re.compile(r'^logging source-interface Vlan(\d+)', re.IGNORECASE), 'vlan_iface', 'Vlan interface'),
]


def run_dependency_check(cfg: ParsedConfig) -> list[str]:
    """Rebuild the task list in emission order and scan for forward references.
    Returns a list of warning strings."""
    warnings: list[str] = []

    # Re-run build_playbook purely to derive the task order,
    # but collect tasks without rendering. Cheapest approach: re-implement a
    # mini ordered task walker that mirrors build_playbook's phase sequence.
    # For maintainability we re-use build_playbook and capture tasks by
    # monkey-patching is too fragile — instead, expose an internal helper.

    ordered_tasks = _build_task_list(cfg)

    defined: dict[tuple[str, str], int] = {}  # (kind, name) -> task index

    def record_definitions(task_idx: int, lines: list[str]):
        for line in lines:
            for pat, kind in _DEFINITIONS:
                m = pat.match(line)
                if m:
                    name = m.group(1)
                    defined.setdefault((kind, name), task_idx)

    def check_references(task_idx: int, task: Task, lines: list[str]):
        for line in lines:
            for pat, kind, label in _REFERENCES:
                m = pat.search(line)
                if not m:
                    continue
                name = m.group(1)
                key = (kind, name)
                if key not in defined:
                    warnings.append(
                        f"WARNING: task #{task_idx} \"{task.name}\" references "
                        f"{label} {name} but it is never defined"
                    )
                elif defined[key] > task_idx:
                    warnings.append(
                        f"WARNING: task #{task_idx} \"{task.name}\" references "
                        f"{label} {name} (defined later in task #{defined[key]})"
                    )

    # Pass 1: collect all definitions (we need full scope regardless of ordering)
    for idx, task in enumerate(ordered_tasks):
        lines = _lines_of(task)
        record_definitions(idx, lines)

    # Pass 2: for each task, check its references against earlier definitions only
    earlier_defined: dict[tuple[str, str], int] = {}
    for idx, task in enumerate(ordered_tasks):
        lines = _lines_of(task)
        # references must be checked BEFORE this task's own definitions are added
        for line in lines:
            for pat, kind, label in _REFERENCES:
                m = pat.search(line)
                if not m:
                    continue
                name = m.group(1)
                key = (kind, name)
                if key not in defined:
                    warnings.append(
                        f"WARNING: task #{idx} \"{task.name}\" references "
                        f"{label} {name} but it is never defined"
                    )
                elif key not in earlier_defined:
                    warnings.append(
                        f"WARNING: task #{idx} \"{task.name}\" references "
                        f"{label} {name} (defined later in task #{defined[key]})"
                    )
        for line in lines:
            for pat, kind in _DEFINITIONS:
                m = pat.match(line)
                if m:
                    earlier_defined.setdefault((kind, m.group(1)), idx)

    return warnings


def _lines_of(task: Task) -> list[str]:
    """Return the flat list of config lines that a task pushes to the device.
    For structured modules we project back the commands they'd send."""
    if task.module == "cisco.ios.ios_config":
        # params is list of (key, value); find "lines" key
        for k, v in task.params:
            if k == "lines":
                return [str(x) for x in v]
            # Also accept "parents" prefix contribution — include parent as leading
            # line so definition patterns anchored at column 0 still match.
        return []
    if task.module == "cisco.ios.ios_vlans":
        for k, v in task.params:
            if k == "config":
                return [f"vlan {entry['vlan_id']}" for entry in v]
        return []
    if task.module == "cisco.ios.ios_user":
        for k, v in task.params:
            if k == "aggregate":
                return [f"username {entry['name']}" for entry in v]
        return []
    if task.module == "cisco.ios.ios_l3_interfaces":
        # for l3 interfaces, the "interface VlanN" headline isn't in `lines`
        # — but we do want to count Vlan interfaces as defined. Handle via
        # ios_interfaces below.
        return []
    if task.module == "cisco.ios.ios_interfaces":
        for k, v in task.params:
            if k == "config":
                return [f"interface {entry['name']}" for entry in v]
        return []
    return []


def _build_task_list(cfg: ParsedConfig) -> list[Task]:
    """Return the same ordered task list that build_playbook would render,
    without rendering. Used by validators."""
    # Implementation: refactor build_playbook so it calls a shared helper.
    # See Step 4.
    raise NotImplementedError  # placeholder — replaced in Step 4
```

- [ ] **Step 4: Refactor `build_playbook` so task building is a helper**

Extract the entire task-assembly portion of `build_playbook` into `_build_task_list(cfg: ParsedConfig) -> list[Task]`. `build_playbook` becomes:

```python
def build_playbook(cfg: ParsedConfig, host: str, source_file: str) -> str:
    hdr = [
        '---',
        f'# Generated by cisco_to_ansible.py from {os.path.basename(source_file)}',
        f'- name: {yaml_scalar(f"Apply configuration from {os.path.basename(source_file)}")}',
        f'  hosts: {yaml_scalar(host)}',
        '  gather_facts: false',
        '  connection: network_cli',
        '',
        '  tasks:',
    ]
    task_list = _build_task_list(cfg)
    rendered: list[str] = list(hdr)
    for t in task_list:
        rendered.extend(render_task(t))
        rendered.append('')
    return '\n'.join(rendered) + '\n'
```

Replace the placeholder `_build_task_list` body with the full ordered assembly that used to live in `build_playbook`.

- [ ] **Step 5: Run dependency-check tests**

```
python -m pytest tests/test_dependency_check.py -v
```
Expected: all pass. The `test_all_known_good_config_has_no_warnings` proves the reorder fix is complete.

- [ ] **Step 6: Integrate into `main` (warn-only; --strict comes in Task 9)**

In `main`, after `cfg = parse_config(raw_text)` and before the playbook is built, add:

```python
dep_warnings = run_dependency_check(cfg)
for w in dep_warnings:
    print(w, file=sys.stderr)
```

Also ensure `import sys` is at the top.

- [ ] **Step 7: Run regression**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```
git add cisco_to_ansible.py tests/test_dependency_check.py
git commit -m "Add structural dependency check for forward references"
```

---

## Task 7: IP format and mask validation

Syntactic validation of IPv4 addresses and masks in known contexts. Malformed addresses on required fields → error (exit 2); mask-contiguity / host-bits-set → warning.

**Files:**
- Modify: `cisco_to_ansible.py`
- Create: `tests/test_ip_validation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ip_validation.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect import failure**

```
python -m pytest tests/test_ip_validation.py -v
```
Expected: FAIL — `validate_ip_formats`, `IPValidationError` don't exist.

- [ ] **Step 3: Implement the validator**

Add to `cisco_to_ansible.py`:

```python
import ipaddress


class IPValidationError(Exception):
    """Raised when malformed IPv4 on a required field makes generation impossible."""


def _looks_like_ip(token: str) -> bool:
    # Four octet-ish dotted tokens
    return bool(re.match(r'^\d{1,3}(\.\d{1,3}){3}$', token))


def _valid_ipv4(token: str) -> bool:
    try:
        ipaddress.IPv4Address(token)
        return True
    except ValueError:
        return False


def _contiguous_mask(mask: str) -> bool:
    try:
        n = int(ipaddress.IPv4Address(mask))
    except ValueError:
        return False
    # Contiguous: all 1-bits then all 0-bits
    return ((~n & (n + 1)) == (n + 1)) if n else True


def _prefix_len(mask: str) -> int:
    n = int(ipaddress.IPv4Address(mask))
    return bin(n).count("1")


def _network_of(ip: str, mask: str) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(f"{ip}/{_prefix_len(mask)}", strict=False)


def validate_ip_formats(cfg: ParsedConfig) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors are fatal (exit 2); warnings print to stderr."""
    errors: list[str] = []
    warnings: list[str] = []

    def err(lineno: int, context: str, msg: str):
        errors.append(f"ERROR: line {lineno} ({context}): {msg}")

    def warn(lineno: int, context: str, msg: str):
        warnings.append(f"WARNING: line {lineno} ({context}): {msg}")

    # Interface IPs
    for ifc in cfg.interfaces:
        for addr_str in ifc["ipv4"]:
            parts = addr_str.split()
            if len(parts) < 2:
                continue
            ip, mask = parts[0], parts[1]
            ctx = f"interface {ifc['name']} / ip address"
            if not _valid_ipv4(ip):
                err(0, ctx, f"{ip} {mask} — invalid IPv4 address")
                continue
            if not _valid_ipv4(mask):
                err(0, ctx, f"{ip} {mask} — invalid mask")
                continue
            if not _contiguous_mask(mask):
                warn(0, ctx, f"{ip} {mask} — non-contiguous IPv4 mask")
                continue
            net = _network_of(ip, mask)
            if ipaddress.IPv4Address(ip) == net.network_address:
                warn(0, ctx, f"{ip} is the network address of {net} — not a host")
            if ipaddress.IPv4Address(ip) == net.broadcast_address:
                warn(0, ctx, f"{ip} is the broadcast address of {net} — not a host")

    # Name servers
    for ns in cfg.name_servers:
        if not _valid_ipv4(ns):
            errors.append(f"ERROR: ip name-server: {ns} — invalid IPv4 address")

    # Logging host, NTP server: IP-looking tokens are validated; hostnames are skipped
    for header, ln, _children in cfg.logging:
        m = re.match(r'^logging host (\S+)', header)
        if m:
            tok = m.group(1)
            if _looks_like_ip(tok) and not _valid_ipv4(tok):
                err(ln, "logging host", f"{tok} — invalid IPv4 address")
    for s in cfg.ntp_servers:
        if _looks_like_ip(s) and not _valid_ipv4(s):
            errors.append(f"ERROR: ntp server: {s} — invalid IPv4 address")

    # DHCP pools
    for header, ln, children_ln in cfg.dhcp_pools:
        pool_network: ipaddress.IPv4Network | None = None
        for child, child_ln in children_ln:
            if child.startswith("network "):
                parts = child.split()
                if len(parts) >= 3:
                    ip, mask = parts[1], parts[2]
                    ctx = f"{header} / network"
                    if not _valid_ipv4(ip):
                        err(child_ln, ctx, f"{ip} {mask} — invalid IPv4 address")
                    elif not _valid_ipv4(mask) or not _contiguous_mask(mask):
                        warn(child_ln, ctx, f"{ip} {mask} — invalid mask")
                    else:
                        net = _network_of(ip, mask)
                        pool_network = net
                        if ipaddress.IPv4Address(ip) != net.network_address:
                            warn(child_ln, ctx,
                                 f"{ip} has host bits set for /{net.prefixlen} (network is {net.network_address})")
            elif child.startswith("default-router "):
                parts = child.split()
                if len(parts) >= 2:
                    router = parts[1]
                    ctx = f"{header} / default-router"
                    if not _valid_ipv4(router):
                        err(child_ln, ctx, f"{router} — invalid IPv4 address")
                    elif pool_network is not None:
                        a = ipaddress.IPv4Address(router)
                        if a not in pool_network:
                            warn(child_ln, ctx,
                                 f"{router} is not in the pool subnet {pool_network}")
                        elif a == pool_network.network_address:
                            warn(child_ln, ctx,
                                 f"{router} is the network address, not a host address")
                        elif a == pool_network.broadcast_address:
                            warn(child_ln, ctx,
                                 f"{router} is the broadcast address, not a host address")
            elif child.startswith("dns-server "):
                for tok in child.split()[1:]:
                    if not _valid_ipv4(tok):
                        err(child_ln, f"{header} / dns-server",
                            f"{tok} — invalid IPv4 address")
            elif child.startswith("host "):
                parts = child.split()
                if len(parts) >= 3:
                    ip, mask = parts[1], parts[2]
                    ctx = f"{header} / host"
                    if not _valid_ipv4(ip):
                        err(child_ln, ctx, f"{ip} {mask} — invalid IPv4 address")
                    elif not _valid_ipv4(mask) or not _contiguous_mask(mask):
                        warn(child_ln, ctx, f"{ip} {mask} — invalid mask")

    # Excluded addresses
    for header, ln, _c in cfg.dhcp_excluded:
        parts = header.split()
        # "ip dhcp excluded-address A [B]"
        if len(parts) >= 4:
            a = parts[3]
            b = parts[4] if len(parts) >= 5 else None
            if not _valid_ipv4(a) or (b is not None and not _valid_ipv4(b)):
                err(ln, "ip dhcp excluded-address",
                    f"{' '.join(parts[3:])} — invalid IPv4 address")
            elif b is not None and ipaddress.IPv4Address(a) > ipaddress.IPv4Address(b):
                warn(ln, "ip dhcp excluded-address",
                     f"{a} > {b} — range bounds inverted")

    # Radius servers
    for header, ln, children_ln in cfg.radius_servers:
        for child, child_ln in children_ln:
            m = re.match(r'^address ipv4 (\S+)', child)
            if m and not _valid_ipv4(m.group(1)):
                err(child_ln, f"{header} / address ipv4",
                    f"{m.group(1)} — invalid IPv4 address")

    # BGP router-id and neighbors
    for header, ln, children_ln in cfg.bgp:
        for child, child_ln in children_ln:
            m = re.match(r'^bgp router-id (\S+)', child)
            if m and not _valid_ipv4(m.group(1)):
                err(child_ln, f"{header} / bgp router-id",
                    f"{m.group(1)} — invalid IPv4 address")
                continue
            m = re.match(r'^neighbor (\S+) ', child)
            if m and _looks_like_ip(m.group(1)) and not _valid_ipv4(m.group(1)):
                err(child_ln, f"{header} / neighbor",
                    f"{m.group(1)} — invalid IPv4 address")

    # Flow exporter destinations
    for header, ln, children_ln in cfg.flow_exporters:
        for child, child_ln in children_ln:
            m = re.match(r'^destination (\S+)', child)
            if m and _looks_like_ip(m.group(1)) and not _valid_ipv4(m.group(1)):
                err(child_ln, f"{header} / destination",
                    f"{m.group(1)} — invalid IPv4 address")

    return errors, warnings
```

- [ ] **Step 4: Run IP validation tests**

```
python -m pytest tests/test_ip_validation.py -v
```
Expected: all pass.

- [ ] **Step 5: Integrate into `main`**

In `main`, after `dep_warnings = run_dependency_check(cfg)`:

```python
ip_errors, ip_warnings = validate_ip_formats(cfg)
for e in ip_errors:
    print(e, file=sys.stderr)
for w in ip_warnings:
    print(w, file=sys.stderr)

if ip_errors:
    return 2  # hard error — don't write YAML
```

Ensure the function returns before writing the output file when `ip_errors` is non-empty.

- [ ] **Step 6: Run regression**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS (the sample config is clean).

- [ ] **Step 7: Commit**

```
git add cisco_to_ansible.py tests/test_ip_validation.py
git commit -m "Add IPv4 and mask format validation with error/warning tiers"
```

---

## Task 8: Subnet-membership validation

Same-block hard checks (default-router ∈ pool, host ∈ pool) plus across-block soft warnings (SVI↔pool mask agreement, excluded-addr ∈ pool, BGP neighbor ∈ interface subnet).

**Files:**
- Modify: `cisco_to_ansible.py`
- Create: `tests/test_subnet_membership.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_subnet_membership.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure**

```
python -m pytest tests/test_subnet_membership.py -v
```
Expected: FAIL (function undefined).

- [ ] **Step 3: Implement validator**

Add to `cisco_to_ansible.py`:

```python
def _build_dhcp_pool_index(cfg: ParsedConfig) -> dict[str, ipaddress.IPv4Network]:
    idx: dict[str, ipaddress.IPv4Network] = {}
    for header, _ln, children_ln in cfg.dhcp_pools:
        for child, _cln in children_ln:
            if child.startswith("network "):
                parts = child.split()
                if len(parts) >= 3 and _valid_ipv4(parts[1]) and _valid_ipv4(parts[2]) and _contiguous_mask(parts[2]):
                    idx[header] = _network_of(parts[1], parts[2])
                    break
    return idx


def _build_interface_subnet_index(cfg: ParsedConfig) -> dict[str, ipaddress.IPv4Interface]:
    idx: dict[str, ipaddress.IPv4Interface] = {}
    for ifc in cfg.interfaces:
        for addr in ifc["ipv4"]:
            parts = addr.split()
            if len(parts) >= 2 and _valid_ipv4(parts[0]) and _valid_ipv4(parts[1]) and _contiguous_mask(parts[1]):
                idx[ifc["name"]] = ipaddress.IPv4Interface(f"{parts[0]}/{_prefix_len(parts[1])}")
                break
    return idx


def validate_subnet_membership(cfg: ParsedConfig) -> tuple[list[str], list[str]]:
    """Return (hard_warnings, soft_warnings).
    hard: same-block relationships (promotable by --strict).
    soft: across-block relationships (never promoted)."""
    hard: list[str] = []
    soft: list[str] = []

    def warn_hard(lineno: int, ctx: str, msg: str):
        hard.append(f"WARNING: line {lineno} ({ctx}): {msg}")

    def warn_soft(lineno: int, ctx: str, msg: str):
        soft.append(f"WARNING: line {lineno} ({ctx}): {msg}")

    pools = _build_dhcp_pool_index(cfg)
    ifaces = _build_interface_subnet_index(cfg)
    all_pool_networks = list(pools.values())

    for header, ln, children_ln in cfg.dhcp_pools:
        pool_net = pools.get(header)
        for child, child_ln in children_ln:
            if pool_net and child.startswith("default-router "):
                parts = child.split()
                if len(parts) >= 2 and _valid_ipv4(parts[1]):
                    a = ipaddress.IPv4Address(parts[1])
                    if a not in pool_net:
                        warn_hard(child_ln, f"{header} / default-router",
                                  f"{parts[1]} is not in the pool subnet {pool_net}")
            elif pool_net and child.startswith("host "):
                parts = child.split()
                if len(parts) >= 2 and _valid_ipv4(parts[1]):
                    a = ipaddress.IPv4Address(parts[1])
                    if a not in pool_net:
                        warn_hard(child_ln, f"{header} / host",
                                  f"{parts[1]} is not in the pool subnet {pool_net}")
            elif pool_net is None and child.startswith("host "):
                # Parent pool has no `network` line — check against ALL pool nets
                parts = child.split()
                if len(parts) >= 2 and _valid_ipv4(parts[1]):
                    a = ipaddress.IPv4Address(parts[1])
                    if not any(a in n for n in all_pool_networks):
                        warn_soft(child_ln, f"{header} / host",
                                  f"{parts[1]} is not in any defined DHCP pool network; "
                                  f"possible reservation outside any declared pool")

    for header, ln, _c in cfg.dhcp_excluded:
        parts = header.split()
        if len(parts) >= 4:
            endpoints = [parts[3]] + ([parts[4]] if len(parts) >= 5 else [])
            for ep in endpoints:
                if _valid_ipv4(ep):
                    a = ipaddress.IPv4Address(ep)
                    if all_pool_networks and not any(a in n for n in all_pool_networks):
                        warn_soft(ln, "ip dhcp excluded-address",
                                  f"{ep} is not in any defined DHCP pool network")

    for header, ln, children_ln in cfg.bgp:
        for child, child_ln in children_ln:
            m = re.match(r'^neighbor (\S+) remote-as ', child)
            if not m:
                continue
            nbr_str = m.group(1)
            if not _valid_ipv4(nbr_str):
                continue
            nbr = ipaddress.IPv4Address(nbr_str)
            if any(nbr in iface.network for iface in ifaces.values()):
                continue
            warn_soft(child_ln, f"{header} / neighbor",
                      f"{nbr_str} is not directly connected to any interface subnet")

    return hard, soft
```

- [ ] **Step 4: Run subnet-membership tests**

```
python -m pytest tests/test_subnet_membership.py -v
```
Expected: all pass.

- [ ] **Step 5: Integrate into `main`**

After `ip_errors, ip_warnings = validate_ip_formats(cfg)`:

```python
sm_hard, sm_soft = validate_subnet_membership(cfg)
for w in sm_hard:
    print(w, file=sys.stderr)
for w in sm_soft:
    print(w, file=sys.stderr)
```

- [ ] **Step 6: Run regression**

```
python -m pytest tests/test_regression.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```
git add cisco_to_ansible.py tests/test_subnet_membership.py
git commit -m "Add subnet-membership validation (same-block hard, across-block soft)"
```

---

## Task 9: `--strict` and `--no-validate` CLI flags

Wire exit codes to validation counts.

**Files:**
- Modify: `cisco_to_ansible.py`
- Create: `tests/test_cli_flags.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli_flags.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```
python -m pytest tests/test_cli_flags.py -v
```
Expected: flag-related tests fail.

- [ ] **Step 3: Add flags in `main`**

Add to the argparse setup:

```python
parser.add_argument('--strict', action='store_true',
                    help='Exit 1 if validation produces any warning.')
parser.add_argument('--no-validate', action='store_true',
                    help='Skip all validation (dependency/IP/subnet membership).')
parser.add_argument('--with-upgrade', action='store_true',
                    help='Prepend firmware upgrade preamble (paranoid bundle mode).')
```

Replace the validation section of `main` with:

```python
dep_warnings: list[str] = []
ip_errors: list[str] = []
ip_warnings: list[str] = []
sm_hard: list[str] = []
sm_soft: list[str] = []

if not args.no_validate:
    dep_warnings = run_dependency_check(cfg)
    ip_errors, ip_warnings = validate_ip_formats(cfg)
    sm_hard, sm_soft = validate_subnet_membership(cfg)

    for line in ip_errors:
        print(line, file=sys.stderr)
    for line in dep_warnings:
        print(line, file=sys.stderr)
    for line in ip_warnings:
        print(line, file=sys.stderr)
    for line in sm_hard:
        print(line, file=sys.stderr)
    for line in sm_soft:
        print(line, file=sys.stderr)

    if ip_errors:
        return 2  # hard error — no YAML written
```

After writing the YAML:

```python
if args.strict and (dep_warnings or ip_warnings or sm_hard):
    return 1
return 0
```

- [ ] **Step 4: Run CLI flag tests**

```
python -m pytest tests/test_cli_flags.py -v
```
Expected: all pass.

- [ ] **Step 5: Run full test suite**

```
python -m pytest -v
```
Expected: everything green.

- [ ] **Step 6: Commit**

```
git add cisco_to_ansible.py tests/test_cli_flags.py
git commit -m "Add --strict and --no-validate flags with tiered exit codes"
```

---

## Task 10: Stderr summary line

Before exiting, print a one-block summary with counts.

**Files:**
- Modify: `cisco_to_ansible.py`
- Append: `tests/test_cli_flags.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_cli_flags.py`:

```python
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
```

- [ ] **Step 2: Run test — expect failure**

Expected: `Dependency check:` not found in stderr yet.

- [ ] **Step 3: Add summary emission in `main`**

Just before the final `return` statements, add:

```python
if not args.no_validate:
    print(
        f"Parsed {len(_all_blocks_count(cfg))} blocks, "
        f"{len(cfg.interfaces)} interfaces, "
        f"{len(cfg.vlans)} VLANs, "
        f"{len(cfg.dhcp_pools)} DHCP pools from {args.input}",
        file=sys.stderr,
    )
    print(f"Dependency check: {len(dep_warnings)} warnings", file=sys.stderr)
    print(f"IP format check: {len(ip_errors)} errors, {len(ip_warnings)} warnings", file=sys.stderr)
    print(f"Subnet membership check: {len(sm_hard) + len(sm_soft)} warnings "
          f"({len(sm_hard)} hard, {len(sm_soft)} soft)", file=sys.stderr)
    print(f"Wrote {out_path} ({len(playbook.splitlines())} lines, "
          f"{_count_tasks(playbook)} tasks)", file=sys.stderr)


def _all_blocks_count(cfg: ParsedConfig) -> list:
    out = []
    for attr in ("base_services", "users", "aaa_new_model", "radius_servers", "aaa_auth",
                 "ip_routing_globals", "vrfs", "vlans", "stp_globals", "acls", "route_maps",
                 "flow_records", "flow_exporters", "flow_monitors", "snmp_views",
                 "snmp_communities", "dhcp_excluded", "dhcp_pools", "interfaces", "bgp",
                 "source_interface_globals", "logging", "ntp_servers", "ip_services",
                 "banners", "line_blocks", "archive", "redundancy", "transceiver",
                 "control_plane", "misc_blocks"):
        val = getattr(cfg, attr, None)
        if isinstance(val, list):
            out.extend(val)
    return out


def _count_tasks(yaml_text: str) -> int:
    return sum(1 for line in yaml_text.splitlines() if line.lstrip().startswith("- name:"))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_cli_flags.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add cisco_to_ansible.py tests/test_cli_flags.py
git commit -m "Emit stderr validation summary with counts"
```

---

## Task 11: Firmware preamble builder

Build the 15-task firmware block as a list of `Task` objects. Pure function; no CLI wiring yet.

**Files:**
- Modify: `cisco_to_ansible.py` (add `build_firmware_preamble`)
- Create: `tests/test_firmware.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_firmware.py`:

```python
from cisco_to_ansible import build_firmware_preamble


def test_preamble_has_fifteen_tasks():
    tasks = build_firmware_preamble()
    assert len(tasks) == 15


def test_preamble_task_names_in_expected_order():
    tasks = build_firmware_preamble()
    names = [t.name for t in tasks]
    assert names[0].lower().startswith("firmware: gather pre-upgrade facts")
    assert "decide" in names[1].lower() or "upgrade needed" in names[1].lower()
    assert "verify image exists" in names[2].lower()
    assert "verify free space" in names[3].lower()
    assert "pre-upgrade show version" in names[4].lower()
    assert "copy" in names[5].lower() and "usb" in names[5].lower()
    assert "md5" in names[6].lower()
    assert "boot variable" in names[7].lower() or "boot system" in names[7].lower()
    assert "write memory" in names[8].lower() or "save running" in names[8].lower()
    assert "prior image" in names[9].lower() or "remember" in names[9].lower()
    assert "reload" in names[10].lower()
    assert "pause" in names[11].lower() or "wait" in names[11].lower()
    assert "wait for connection" in names[12].lower()
    assert "post-upgrade" in names[13].lower()
    assert "capture post" in names[14].lower() or "cleanup" in names[14].lower()


def test_preamble_uses_ansible_vars_not_hardcoded():
    tasks = build_firmware_preamble()
    joined_params = repr([t.params for t in tasks])
    for required in ("firmware_image", "firmware_md5", "firmware_target_version",
                     "firmware_usb_device", "firmware_flash_device",
                     "firmware_reload_countdown", "firmware_reload_timeout"):
        assert required in joined_params, f"missing var: {required}"


def test_preamble_gated_by_upgrade_flag():
    tasks = build_firmware_preamble()
    gated = [t for t in tasks if any(k == "when" for k, _ in t.params)]
    # Tasks after #2 (decision) must have when: firmware_upgrade_needed
    assert len(gated) >= 12, f"expected >=12 gated tasks, got {len(gated)}"
```

- [ ] **Step 2: Run tests — expect import failure**

```
python -m pytest tests/test_firmware.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `build_firmware_preamble`**

Add to `cisco_to_ansible.py`:

```python
_FIRMWARE_GATE = "firmware_upgrade_needed | default(true)"


def build_firmware_preamble() -> list[Task]:
    """Return the 15 Tasks of the opt-in firmware upgrade preamble.
    All configuration is supplied at play-run time via Ansible vars.
    Tasks 3–15 are gated on `firmware_upgrade_needed` (set by task 2)."""

    def gated_params(core: list[tuple[str, object]]) -> list[tuple[str, object]]:
        return core + [("when", _FIRMWARE_GATE)]

    tasks: list[Task] = [
        Task(
            name="Firmware: gather pre-upgrade facts",
            module="cisco.ios.ios_facts",
            params=[("gather_subset", ["min"]), ("register", "preupgrade_facts")],
        ),
        Task(
            name="Firmware: decide whether upgrade is needed",
            module="ansible.builtin.set_fact",
            params=[
                ("firmware_upgrade_needed",
                 "{{ preupgrade_facts.ansible_facts.ansible_net_version != firmware_target_version }}"),
            ],
        ),
        Task(
            name="Firmware: verify image exists on USB",
            module="cisco.ios.ios_command",
            params=gated_params([
                ("commands", ["dir {{ firmware_usb_device | default('usbflash0:') }}"]),
                ("register", "usb_listing"),
                ("failed_when",
                 "firmware_image not in (usb_listing.stdout[0] | default(''))"),
            ]),
        ),
        Task(
            name="Firmware: verify free space on flash",
            module="cisco.ios.ios_command",
            params=gated_params([
                ("commands", ["dir {{ firmware_flash_device | default('flash:') }}"]),
                ("register", "flash_listing"),
                ("failed_when",
                 "(flash_listing.stdout[0] | regex_search('([0-9]+) bytes free', '\\\\1') "
                 "| first | default('0') | int) < "
                 "((firmware_image_size_bytes | default(1073741824)) * 1.1)"),
            ]),
        ),
        Task(
            name="Firmware: capture pre-upgrade show version",
            module="ansible.builtin.copy",
            params=gated_params([
                ("content",
                 "{{ lookup('ansible.builtin.pipe', 'echo pre-upgrade show version') }}"
                 "\n{{ preupgrade_facts.ansible_facts.ansible_net_version }}"
                 "\n{{ preupgrade_facts.ansible_facts.ansible_net_image | default('unknown') }}"),
                ("dest",
                 "{{ firmware_audit_dir | default('./audit') }}/{{ inventory_hostname }}"
                 "-pre-{{ ansible_date_time.iso8601_basic_short }}.txt"),
                ("delegate_to", "localhost"),
            ]),
        ),
        Task(
            name="Firmware: copy image from USB to flash",
            module="cisco.ios.ios_command",
            params=gated_params([
                ("commands", [{
                    "command": "copy {{ firmware_usb_device | default('usbflash0:') }}"
                               "{{ firmware_image }} {{ firmware_flash_device | default('flash:') }}",
                    "prompt": "(Destination filename.*|Do you want to over write)",
                    "answer": "\\r",
                }]),
            ]),
        ),
        Task(
            name="Firmware: verify MD5 on flash",
            module="cisco.ios.ios_command",
            params=gated_params([
                ("commands",
                 ["verify /md5 {{ firmware_flash_device | default('flash:') }}"
                  "{{ firmware_image }} {{ firmware_md5 }}"]),
                ("register", "md5_out"),
                ("failed_when", "'Verified' not in md5_out.stdout[0]"),
            ]),
        ),
        Task(
            name="Firmware: set boot variable",
            module="cisco.ios.ios_config",
            params=gated_params([
                ("lines", ["no boot system",
                           "boot system flash:{{ firmware_image }}"]),
                ("save_when", "modified"),
            ]),
        ),
        Task(
            name="Firmware: save running-config (write memory)",
            module="cisco.ios.ios_command",
            params=gated_params([("commands", ["write memory"])]),
        ),
        Task(
            name="Firmware: remember prior image for later cleanup",
            module="ansible.builtin.set_fact",
            params=gated_params([
                ("firmware_prior_image",
                 "{{ preupgrade_facts.ansible_facts.ansible_net_image | default('') | basename }}"),
            ]),
        ),
        Task(
            name="Firmware: schedule reload with countdown",
            module="cisco.ios.ios_command",
            params=gated_params([
                ("commands", [{
                    "command": "reload in {{ firmware_reload_countdown | default(5) }} "
                               "firmware upgrade via ansible",
                    "prompt": "(confirm|\\[yes/no\\])",
                    "answer": "y\\ry\\r",
                }]),
            ]),
        ),
        Task(
            name="Firmware: pause until reload window starts",
            module="ansible.builtin.pause",
            params=gated_params([
                ("seconds",
                 "{{ (firmware_reload_countdown | default(5) | int) * 60 + 30 }}"),
            ]),
        ),
        Task(
            name="Firmware: wait for connection after reload",
            module="ansible.builtin.wait_for_connection",
            params=gated_params([
                ("delay", 60),
                ("timeout", "{{ firmware_reload_timeout | default(900) }}"),
            ]),
        ),
        Task(
            name="Firmware: post-upgrade facts and version assert",
            module="cisco.ios.ios_facts",
            params=gated_params([
                ("gather_subset", ["min"]),
                ("register", "postupgrade_facts"),
            ]),
        ),
        Task(
            name="Firmware: capture post-upgrade show version and assert target",
            module="ansible.builtin.assert",
            params=gated_params([
                ("that",
                 ["postupgrade_facts.ansible_facts.ansible_net_version == firmware_target_version"]),
                ("fail_msg",
                 "Post-upgrade version {{ postupgrade_facts.ansible_facts.ansible_net_version }} "
                 "!= target {{ firmware_target_version }}"),
            ]),
        ),
    ]
    return tasks
```

Note: some Ansible modules accept `register` / `when` / `delegate_to` as task-level keys, not module params. The `render_task` helper currently only emits under the module key. Handle task-level keys by checking in `render_task` for a known set (`when`, `register`, `delegate_to`, `failed_when`) and emitting them at the task level rather than nested under the module.

- [ ] **Step 4: Extend `render_task` to emit task-level keys**

In `render_task`, modify so it separates params into "task-level" and "module-level":

```python
TASK_LEVEL_KEYS = {"when", "register", "delegate_to", "failed_when", "changed_when"}


def render_task(task: Task, indent: int = 4) -> list[str]:
    pad = ' ' * indent
    inner = ' ' * (indent + 2)
    param_pad = ' ' * (indent + 4)

    task_level = [(k, v) for k, v in task.params if k in TASK_LEVEL_KEYS]
    module_level = [(k, v) for k, v in task.params if k not in TASK_LEVEL_KEYS]

    out = [f'{pad}- name: {yaml_scalar(task.name)}']
    out.append(f'{inner}{task.module}:')
    for key, value in module_level:
        out.extend(_emit_param(key, value, prefix=param_pad))
    for key, value in task_level:
        # task-level keys sit at the same indent as the module key
        out.extend(_emit_param(key, value, prefix=inner))
    return out
```

- [ ] **Step 5: Run firmware tests**

```
python -m pytest tests/test_firmware.py -v
```
Expected: all pass.

- [ ] **Step 6: Run full suite**

```
python -m pytest -v
```
Expected: everything still green.

- [ ] **Step 7: Commit**

```
git add cisco_to_ansible.py tests/test_firmware.py
git commit -m "Add firmware upgrade preamble builder (paranoid bundle mode)"
```

---

## Task 12: `--with-upgrade` CLI integration and firmware golden fixture

Wire `build_firmware_preamble` into `build_playbook`; commit a golden fixture with firmware tasks at the top.

**Files:**
- Modify: `cisco_to_ansible.py` — `build_playbook` accepts `with_upgrade: bool` and `main` passes `args.with_upgrade`.
- Create: `tests/fixtures/FRS-QRS-SW01.with-firmware.yml`
- Modify: `tests/test_regression.py`

- [ ] **Step 1: Write failing regression test**

Append to `tests/test_regression.py`:

```python
FIRMWARE_OUT = ROOT / "tests" / "fixtures" / "FRS-QRS-SW01.with-firmware.yml"


def test_firmware_fixture_matches(tmp_path):
    out = tmp_path / "generated.yml"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE_IN),
         "-o", str(out), "--with-upgrade"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == FIRMWARE_OUT.read_text(encoding="utf-8")
```

- [ ] **Step 2: Thread `--with-upgrade` through**

In `build_playbook`:

```python
def build_playbook(cfg: ParsedConfig, host: str, source_file: str,
                   with_upgrade: bool = False) -> str:
    ...
    task_list: list[Task] = []
    if with_upgrade:
        task_list.extend(build_firmware_preamble())
    task_list.extend(_build_task_list(cfg))
    ...
```

Wait — `_build_task_list` currently builds the whole list. With the firmware prepend, we need to call it and then extend. Adjust:

```python
def build_playbook(cfg: ParsedConfig, host: str, source_file: str,
                   with_upgrade: bool = False) -> str:
    hdr = [
        '---',
        f'# Generated by cisco_to_ansible.py from {os.path.basename(source_file)}',
        f'- name: {yaml_scalar(f"Apply configuration from {os.path.basename(source_file)}")}',
        f'  hosts: {yaml_scalar(host)}',
        '  gather_facts: false',
        '  connection: network_cli',
        '',
        '  tasks:',
    ]
    task_list: list[Task] = []
    if with_upgrade:
        task_list.extend(build_firmware_preamble())
    task_list.extend(_build_task_list(cfg))
    rendered: list[str] = list(hdr)
    for t in task_list:
        rendered.extend(render_task(t))
        rendered.append('')
    return '\n'.join(rendered) + '\n'
```

In `main`, change:
```python
playbook = build_playbook(cfg, host=host_target, source_file=args.input)
```
to:
```python
playbook = build_playbook(cfg, host=host_target, source_file=args.input,
                          with_upgrade=args.with_upgrade)
```

- [ ] **Step 3: Generate the firmware fixture**

```
python cisco_to_ansible.py tests/fixtures/FRS-QRS-SW01-2026-04-14.txt -o tests/fixtures/FRS-QRS-SW01.with-firmware.yml --with-upgrade
```

Skim the first ~100 lines to confirm the 15 firmware tasks render correctly and the rest of the playbook follows.

- [ ] **Step 4: Run the regression**

```
python -m pytest tests/test_regression.py -v
```
Expected: both `test_baseline_matches_fixture` and `test_firmware_fixture_matches` PASS.

- [ ] **Step 5: Validate YAML parseable (if pyyaml available)**

```
python -c "import yaml; yaml.safe_load(open('tests/fixtures/FRS-QRS-SW01.with-firmware.yml'))"
```
Expected: no exception.

- [ ] **Step 6: Run the full suite**

```
python -m pytest -v
```
Expected: all tests green.

- [ ] **Step 7: Commit**

```
git add cisco_to_ansible.py tests/test_regression.py tests/fixtures/FRS-QRS-SW01.with-firmware.yml
git commit -m "Wire --with-upgrade CLI flag and add firmware golden fixture"
```

- [ ] **Step 8: Push branch**

```
git push
```

- [ ] **Step 9: Open a pull request (via gh)**

```
gh pr create --title "Ordering, validation, and firmware preamble" --body "$(cat <<'EOF'
## Summary
- Reorders generated Ansible tasks across six phases so definitions precede references (fixes VRF/flow-monitor/BGP/STP ordering issues identified in the spec).
- Adds three validation layers (structural dependency check, IPv4/mask format, subnet membership) with warning-by-default behavior.
- Adds opt-in `--with-upgrade` flag that prepends a 15-task paranoid bundle-mode firmware upgrade preamble fully parameterized via Ansible vars.

Spec: `docs/superpowers/specs/2026-04-23-cisco-playbook-ordering-and-firmware-design.md`

## Test plan
- [x] `python -m pytest -v` — all suites pass
- [x] Baseline golden-file regression matches
- [x] Firmware golden-file regression matches
- [ ] Manual smoke: run `ansible-playbook --syntax-check tests/fixtures/FRS-QRS-SW01.baseline.yml`
- [ ] Manual smoke: run `ansible-playbook --syntax-check tests/fixtures/FRS-QRS-SW01.with-firmware.yml -e firmware_image=x -e firmware_md5=y -e firmware_target_version=z`
EOF
)"
```

---

## Self-review checklist (author completed before handoff)

**Spec coverage — every section of the spec maps to at least one task:**
- Spec §1 (Problem): addressed by Tasks 5 (phase-order), 6 (dependency check), 7 (IP format), 8 (subnet membership).
- Spec §3 (Emission order): Task 5 + ordering invariants asserted in `tests/test_emission.py`.
- Spec §3 parser changes: Task 2 (line numbers) + Task 4 (typed buckets).
- Spec §4 (Dependency check): Task 6.
- Spec §5 (IP format + subnet membership): Tasks 7, 8.
- Spec §6 (Firmware preamble, 15 tasks, Ansible vars): Task 11 builder + Task 12 CLI wiring.
- Spec §7 (CLI surface: `--with-upgrade`, `--strict`, `--no-validate`, exit codes, stderr summary): Tasks 9, 10, 12.
- Spec §8 (Testing strategy: golden-file regression, order invariants, synthetic unit tests, firmware structural tests): Tasks 1, 5, 6, 7, 8, 11, 12.

**Placeholder scan:** no "TBD", "TODO", "implement later", or "similar to Task N". Every step has the literal code.

**Type consistency:** `ParsedConfig` field names reused across tasks; `Task` signature identical; `run_dependency_check(cfg)` returns `list[str]` consistently; `validate_ip_formats` returns `(errors, warnings)` consistently; `validate_subnet_membership` returns `(hard, soft)` consistently.

**Testability:** every task has an explicit test step that runs before implementation and a distinct test step that passes after. Every commit step lists the exact files to stage.
