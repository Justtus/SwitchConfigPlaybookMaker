#!/usr/bin/env python3
"""Convert a Cisco IOS / IOS-XE switch configuration file into an Ansible playbook.

Usage:
    python cisco_to_ansible.py <input.txt> [-o output.yml] [--host HOST] [--group GROUP]

Structured elements (hostname, domain/name-servers, VLANs, users, banner, L2/L3
interface properties) are emitted with dedicated cisco.ios.* modules. Everything
else falls back to cisco.ios.ios_config tasks, preserving parent/child scoping.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def extract_banners(lines: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Pull any `banner <kind> ^X ... ^X` blocks out of the raw line list.

    Returns (banners, remaining_lines). `banners` is a list of (kind, text).
    """
    banners: list[tuple[str, str]] = []
    remaining: list[str] = []
    i = 0
    banner_start = re.compile(r'^banner\s+(\S+)\s+(\S+)\s*$')
    while i < len(lines):
        line = lines[i]
        m = banner_start.match(line.rstrip())
        if not m:
            remaining.append(line)
            i += 1
            continue
        kind, marker = m.group(1), m.group(2)
        # Common Cisco form: marker is literal "^C" (caret + C), but also honour
        # any single delimiter token by matching the same token.
        body: list[str] = []
        i += 1
        while i < len(lines):
            this = lines[i].rstrip('\r\n')
            if this.rstrip().endswith(marker):
                trimmed = this.rstrip()[: -len(marker)].rstrip()
                if trimmed:
                    body.append(trimmed)
                i += 1
                break
            body.append(this)
            i += 1
        banners.append((kind, '\n'.join(body)))
    return banners, remaining


def parse_blocks(lines: Iterable[str]) -> list[tuple[str, int, list[tuple[str, int]]]]:
    """Split config into (header, header_lineno, [(child, child_lineno)]) blocks.

    A block is introduced by a line starting in column 0 and continues while
    following lines are indented. Blank lines and bang-comment lines ('!') end
    the current block. Children are stripped of leading whitespace but keep
    internal spacing. Line numbers are 1-indexed source positions.
    """
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


# ---------------------------------------------------------------------------
# Structured extractors
# ---------------------------------------------------------------------------

def parse_interface(header: str, children: list[str]) -> dict:
    name = header.split(None, 1)[1]
    iface: dict = {
        'name': name,
        'description': None,
        'enabled': True,
        'mode': None,
        'access_vlan': None,
        'voice_vlan': None,
        'trunk_native': None,
        'trunk_allowed': None,
        'ipv4': [],
        'vrf': None,
        'extras': [],
    }
    for c in children:
        if c.startswith('description '):
            iface['description'] = c[len('description '):]
        elif c == 'shutdown':
            iface['enabled'] = False
        elif c == 'no shutdown':
            iface['enabled'] = True
        elif c.startswith('switchport access vlan '):
            iface['access_vlan'] = int(c.split()[-1])
            if iface['mode'] is None:
                iface['mode'] = 'access'
        elif c.startswith('switchport voice vlan '):
            iface['voice_vlan'] = int(c.split()[-1])
        elif c.startswith('switchport trunk native vlan '):
            iface['trunk_native'] = int(c.split()[-1])
        elif c.startswith('switchport trunk allowed vlan '):
            iface['trunk_allowed'] = c[len('switchport trunk allowed vlan '):]
        elif c == 'switchport mode trunk':
            iface['mode'] = 'trunk'
        elif c == 'switchport mode access':
            iface['mode'] = 'access'
        elif c.startswith('ip address '):
            rest = c[len('ip address '):].strip()
            if rest and rest != 'dhcp':
                iface['ipv4'].append(rest)
        elif c == 'no ip address':
            pass
        elif c.startswith('vrf forwarding '):
            iface['vrf'] = c[len('vrf forwarding '):]
        else:
            iface['extras'].append(c)
    return iface


VLAN_INLINE = re.compile(r'^vlan\s+(\d+)\s+name\s+(.+?)\s*$', re.IGNORECASE)


def parse_username(line: str) -> dict | None:
    """Parse `username NAME [privilege N] [secret [TYPE] VALUE | password ...]`."""
    m = re.match(
        r'^username\s+(\S+)'
        r'(?:\s+privilege\s+(\d+))?'
        r'(?:\s+(secret|password)\s+(?:(\d+)\s+)?(.+))?\s*$',
        line,
    )
    if not m:
        return None
    name, priv, kw, ptype, pval = m.groups()
    entry: dict = {'name': name}
    if priv is not None:
        entry['privilege'] = int(priv)
    if kw:
        entry['secret'] = (kw == 'secret')
        if ptype is not None:
            entry['hash_type'] = int(ptype)
        entry['value'] = pval.strip()
    return entry


# ---------------------------------------------------------------------------
# YAML emission (hand-written to avoid a PyYAML dependency)
# ---------------------------------------------------------------------------

_SAFE_SCALAR = re.compile(r'^[A-Za-z0-9_./\-]+$')
_RESERVED = {'yes', 'no', 'true', 'false', 'null', '~', 'on', 'off', 'y', 'n'}


def yaml_scalar(value) -> str:
    """Render a Python scalar as a YAML scalar, quoting when necessary."""
    if value is None:
        return '~'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, int):
        return str(value)
    s = str(value)
    if s == '':
        return '""'
    if s.lower() in _RESERVED:
        return f'"{s}"'
    if _SAFE_SCALAR.match(s) and not s[0].isdigit():
        return s
    # default to double-quoted with minimal escaping
    escaped = s.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def yaml_block_literal(text: str, indent: int) -> str:
    """Emit a block literal scalar (|) preserving embedded newlines."""
    pad = ' ' * indent
    if text == '':
        return '|\n' + pad
    out = ['|']
    for line in text.split('\n'):
        out.append(pad + line)
    return '\n'.join(out)


def emit_task(name: str, module: str, params: list[tuple[str, object]], indent: int = 4) -> list[str]:
    """Return lines for one task. `params` are rendered in order."""
    pad = ' ' * indent
    inner = ' ' * (indent + 2)
    param_pad = ' ' * (indent + 4)
    out = [f'{pad}- name: {yaml_scalar(name)}']
    out.append(f'{inner}{module}:')
    for key, value in params:
        out.extend(_emit_param(key, value, prefix=param_pad))
    out.append('')
    return out


def _emit_param(key: str, value, prefix: str) -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        lines.append(f'{prefix}{key}:')
        for k, v in value.items():
            lines.extend(_emit_param(k, v, prefix + '  '))
    elif isinstance(value, list):
        if not value:
            lines.append(f'{prefix}{key}: []')
            return lines
        lines.append(f'{prefix}{key}:')
        item_prefix = prefix + '  '
        for item in value:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    if first:
                        sub = _emit_param(k, v, item_prefix + '  ')
                        # Replace the leading indent of first sub line with "- "
                        if sub:
                            sub[0] = item_prefix + '- ' + sub[0][len(item_prefix) + 2:]
                        lines.extend(sub)
                        first = False
                    else:
                        lines.extend(_emit_param(k, v, item_prefix + '  '))
            else:
                lines.append(f'{item_prefix}- {yaml_scalar(item)}')
    elif isinstance(value, str) and '\n' in value:
        lines.append(f'{prefix}{key}: {yaml_block_literal(value, len(prefix) + 2)}')
    else:
        lines.append(f'{prefix}{key}: {yaml_scalar(value)}')
    return lines


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


# ---------------------------------------------------------------------------
# Block classifier and typed-bucket parser
# ---------------------------------------------------------------------------


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
            # Cisco `username` commands are always one-liners (no indented children).
            # If we ever see children here, the input is malformed — route to
            # misc_blocks rather than silently discarding.
            if not children:
                u = parse_username(header)
                if u is not None:
                    cfg.users.append(u)
            else:
                cfg.misc_blocks.append((header, header_ln, children_with_ln))
            continue
        if bucket == "ntp":
            if header.startswith("ntp server "):
                parts = header.split(None, 2)
                if len(parts) >= 3:
                    cfg.ntp_servers.append(parts[2].strip())
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


# ---------------------------------------------------------------------------
# Playbook builder
# ---------------------------------------------------------------------------

def _build_task_list(cfg: ParsedConfig) -> list[Task]:
    """Return the same ordered task list that build_playbook would render,
    without rendering. Used by validators."""
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
        if not cleaned:
            continue
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
    for bucket in (cfg.acls, cfg.route_maps, cfg.flow_records,
                   cfg.flow_exporters, cfg.flow_monitors):
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

    return task_list


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


# ---------------------------------------------------------------------------
# IP format and mask validation
# ---------------------------------------------------------------------------

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
    # Contiguous: complement (32-bit NOT) must be all trailing 1s, i.e. (c & (c+1)) == 0
    c = (~n) & 0xFFFFFFFF
    return (c & (c + 1)) == 0


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


# ---------------------------------------------------------------------------
# Dependency check (structural validation)
# ---------------------------------------------------------------------------

# Each row: (compiled_regex, kind-key). The regex's group(1) must capture the
# entity name. Kind-keys are matched against _REFERENCES rows.
_DEFINITIONS = [
    (re.compile(r'^vrf definition (\S+)'), 'vrf'),
    (re.compile(r'^flow (?:record|exporter|monitor) (\S+)'), 'flow'),
    (re.compile(r'^ip access-list (?:standard|extended) (\S+)'), 'acl'),
    (re.compile(r'^route-map (\S+)'), 'route_map'),
    (re.compile(r'^radius server (\S+)'), 'radius'),   # tracked for future aaa-group reference checks
    (re.compile(r'^snmp-server view (\S+)'), 'snmp_view'),
    (re.compile(r'^interface Vlan(\d+)', re.IGNORECASE), 'vlan_iface'),
    (re.compile(r'^username (\S+)'), 'user'),           # tracked for future auth reference checks
]

# Reference patterns applied to every config line produced by _lines_of for
# each task (ios_config, ios_vlans, ios_user, ios_interfaces, etc.).
# Each pattern's group(1) captures the referenced entity name.
# Each row: (compiled_regex, kind-key, label). label is the human-readable
# type name used in warning text.
_REFERENCES = [
    (re.compile(r'^vrf forwarding (\S+)'), 'vrf', 'VRF'),
    (re.compile(r'^ip flow monitor (\S+) (?:input|output)'), 'flow', 'flow monitor'),
    (re.compile(r'^match ip address (\S+)'), 'acl', 'ACL'),
    (re.compile(r'neighbor \S+ route-map (\S+) (?:in|out)'), 'route_map', 'route-map'),
    (re.compile(r'^snmp-server community \S+ view (\S+)'), 'snmp_view', 'SNMP view'),
    (re.compile(r'^ip radius source-interface Vlan(\d+)', re.IGNORECASE), 'vlan_iface', 'Vlan interface'),
    (re.compile(r'^logging source-interface Vlan(\d+)', re.IGNORECASE), 'vlan_iface', 'Vlan interface'),
]


def _lines_of(task: Task) -> list[str]:
    """Return the flat list of config lines that a task pushes to the device.
    For structured modules we project back the commands they'd send."""
    if task.module == "cisco.ios.ios_config":
        # params is list of (key, value); collect "parents" and "lines"
        parents_val: list[str] = []
        lines_val: list[str] = []
        for k, v in task.params:
            if k == "parents":
                # parents may be a single string or a list
                if isinstance(v, list):
                    parents_val = [str(x) for x in v]
                else:
                    parents_val = [str(v)]
            elif k == "lines":
                lines_val = [str(x) for x in v]
        # Include parents first so definition patterns anchored at col 0 match
        # block headers (e.g. "vrf definition MGMT", "flow monitor MON1").
        return parents_val + lines_val
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
    # Unknown or read-only modules (ios_facts, ios_command, set_fact, etc.)
    # produce no config lines; ignore them.
    return []


def run_dependency_check(cfg: ParsedConfig) -> list[str]:
    """Rebuild the task list in emission order and scan for forward references.
    Returns a list of warning strings."""
    warnings: list[str] = []

    ordered_tasks = _build_task_list(cfg)

    # Pass 1: collect all definitions (to detect "never defined" vs "defined later")
    defined: dict[tuple[str, str], int] = {}
    for idx, task in enumerate(ordered_tasks):
        lines = _lines_of(task)
        for line in lines:
            for pat, kind in _DEFINITIONS:
                m = pat.match(line)
                if m:
                    name = m.group(1)
                    defined.setdefault((kind, name), idx)

    # Pass 2: walk tasks in order, check references against only earlier definitions
    earlier_defined: dict[tuple[str, str], int] = {}
    for idx, task in enumerate(ordered_tasks):
        lines = _lines_of(task)
        # references must be checked BEFORE this task's own definitions are added
        seen_in_task: set[tuple[str, str]] = set()
        for line in lines:
            for pat, kind, label in _REFERENCES:
                m = pat.search(line)
                if not m:
                    continue
                name = m.group(1)
                key = (kind, name)
                if key not in seen_in_task:
                    if key not in defined:
                        warnings.append(
                            f"WARNING: task #{idx} \"{task.name}\" references "
                            f"{label} {name} but it is never defined"
                        )
                    elif key not in earlier_defined and defined[key] != idx:
                        warnings.append(
                            f"WARNING: task #{idx} \"{task.name}\" references "
                            f"{label} {name} (defined later in task #{defined[key]})"
                        )
                seen_in_task.add(key)
        for line in lines:
            for pat, kind in _DEFINITIONS:
                m = pat.match(line)
                if m:
                    earlier_defined.setdefault((kind, m.group(1)), idx)

    return warnings


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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Convert a Cisco IOS config file into an Ansible playbook.'
    )
    parser.add_argument('input', help='Path to the Cisco switch config text file.')
    parser.add_argument('-o', '--output',
                        help='Output playbook path. Defaults to <input-stem>.yml '
                             'in the current working directory.')
    parser.add_argument('--host',
                        help='Inventory host or group the playbook should target. '
                             'Defaults to the configured hostname, or "switches".')
    args = parser.parse_args(argv)

    with open(args.input, 'r', encoding='utf-8', errors='replace') as fh:
        raw_text = fh.read()

    cfg = parse_config(raw_text)
    dep_warnings = run_dependency_check(cfg)
    for w in dep_warnings:
        print(w, file=sys.stderr)

    ip_errors, ip_warnings = validate_ip_formats(cfg)
    for e in ip_errors:
        print(e, file=sys.stderr)
    for w in ip_warnings:
        print(w, file=sys.stderr)

    if ip_errors:
        return 2  # hard error — don't write YAML

    host_target = args.host or cfg.hostname or 'switches'
    playbook = build_playbook(cfg, host=host_target, source_file=args.input)

    out_path = args.output
    if out_path is None:
        stem = os.path.splitext(os.path.basename(args.input))[0]
        out_path = f'{stem}.yml'

    with open(out_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(playbook)

    print(f'Wrote {out_path} ({len(playbook.splitlines())} lines).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
