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
# Playbook builder
# ---------------------------------------------------------------------------

def build_playbook(blocks: list[tuple[str, int, list[tuple[str, int]]]],
                   banners: list[tuple[str, str]],
                   host: str,
                   source_file: str) -> str:

    hostname: str | None = None
    domain_name: str | None = None
    name_servers: list[str] = []
    ntp_servers: list[str] = []
    logging_lines: list[str] = []
    vlans: list[dict] = []
    users: list[dict] = []
    interfaces: list[dict] = []
    globals_simple: list[str] = []
    raw_blocks: list[tuple[str, list[str]]] = []

    # Top-level one-liners we'd like to keep together in the "globals" bucket.
    GLOBAL_PREFIXES = (
        'service ', 'no service ', 'platform ', 'no platform ',
        'aaa ', 'no aaa ', 'clock ', 'ip routing', 'no ip routing',
        'ip forward-protocol', 'ip http', 'no ip http', 'ip ftp',
        'ip radius', 'login ', 'no login ', 'spanning-tree ',
        'diagnostic ', 'transceiver ', 'memory ',
        'snmp-server ', 'no snmp-server ', 'no device-tracking ',
        'logging buffered', 'logging source-interface', 'logging host',
        'logging ',
    )

    for header, header_lineno, children_with_ln in blocks:
        children = [c for c, _ln in children_with_ln]
        # pure one-line entries
        if not children:
            line = header.strip()
            if line in ('end', '!'):
                # `end` terminates the config text; `!` is a bare comment.
                continue

            if line.startswith('hostname '):
                hostname = line.split(None, 1)[1].strip()
                continue

            if line.startswith('ip domain name '):
                domain_name = line[len('ip domain name '):].strip()
                continue

            if line.startswith('ip name-server '):
                name_servers.extend(line.split()[2:])
                continue

            if line.startswith('ntp server '):
                ntp_servers.append(line.split(None, 2)[2].strip())
                continue

            if line.startswith('logging '):
                logging_lines.append(line)
                continue

            m = VLAN_INLINE.match(line)
            if m:
                vlans.append({'vlan_id': int(m.group(1)), 'name': m.group(2).strip()})
                continue

            if line.startswith('username '):
                u = parse_username(line)
                if u is not None:
                    users.append(u)
                    continue

            if line.startswith(GLOBAL_PREFIXES):
                globals_simple.append(line)
                continue

            # unknown one-liner — keep it in globals
            globals_simple.append(line)
            continue

        # block with children
        if header.startswith('interface '):
            interfaces.append(parse_interface(header, children))
            continue

        raw_blocks.append((header, children))

    # Assemble tasks --------------------------------------------------------

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

    if hostname:
        task_list.append(Task(
            name=f'Configure hostname {hostname}',
            module='cisco.ios.ios_hostname',
            params=[('config', {'hostname': hostname}), ('state', 'merged')],
        ))

    if domain_name or name_servers:
        params = []
        system: dict = {}
        if hostname:
            system['hostname'] = hostname
        if domain_name:
            system['domain_name'] = domain_name
        if name_servers:
            system['name_servers'] = name_servers
        params.append(('config', system))
        params.append(('state', 'merged'))
        task_list.append(Task(
            name='Configure domain and name servers',
            module='cisco.ios.ios_system',
            params=params,
        ))

    if vlans:
        task_list.append(Task(
            name='Configure VLAN database',
            module='cisco.ios.ios_vlans',
            params=[('config', vlans), ('state', 'merged')],
        ))

    # Interfaces split across three structured modules + raw residue.
    if interfaces:
        iface_state = []
        l2_cfg = []
        l3_cfg = []
        for ifc in interfaces:
            state_entry: dict = {'name': ifc['name']}
            if ifc['description'] is not None:
                state_entry['description'] = ifc['description']
            state_entry['enabled'] = ifc['enabled']
            iface_state.append(state_entry)

            if any(ifc[k] is not None for k in ('mode', 'access_vlan', 'voice_vlan',
                                                'trunk_native', 'trunk_allowed')):
                l2_entry: dict = {'name': ifc['name']}
                if ifc['mode']:
                    l2_entry['mode'] = ifc['mode']
                if ifc['access_vlan'] is not None:
                    l2_entry['access'] = {'vlan': ifc['access_vlan']}
                if ifc['voice_vlan'] is not None:
                    l2_entry['voice'] = {'vlan': ifc['voice_vlan']}
                trunk: dict = {}
                if ifc['trunk_native'] is not None:
                    trunk['native_vlan'] = ifc['trunk_native']
                if ifc['trunk_allowed']:
                    trunk['allowed_vlans'] = ifc['trunk_allowed']
                if trunk:
                    l2_entry['trunk'] = trunk
                l2_cfg.append(l2_entry)

            if ifc['ipv4']:
                l3_entry: dict = {'name': ifc['name'],
                                  'ipv4': [{'address': a} for a in ifc['ipv4']]}
                l3_cfg.append(l3_entry)

        task_list.append(Task(
            name='Configure interface admin state and descriptions',
            module='cisco.ios.ios_interfaces',
            params=[('config', iface_state), ('state', 'merged')],
        ))

        if l2_cfg:
            task_list.append(Task(
                name='Configure L2 interface properties (switchport)',
                module='cisco.ios.ios_l2_interfaces',
                params=[('config', l2_cfg), ('state', 'merged')],
            ))

        if l3_cfg:
            task_list.append(Task(
                name='Configure L3 interface addressing',
                module='cisco.ios.ios_l3_interfaces',
                params=[('config', l3_cfg), ('state', 'merged')],
            ))

        # Residual interface lines that the structured modules don't cover
        # (e.g. `ip flow monitor ...`, `auto qos trust dscp`,
        # `spanning-tree portfast`, `negotiation auto`, `vrf forwarding ...`).
        for ifc in interfaces:
            residue = list(ifc['extras'])
            if ifc['vrf']:
                residue.insert(0, f"vrf forwarding {ifc['vrf']}")
            if not residue:
                continue
            task_list.append(Task(
                name=f"Apply remaining commands on interface {ifc['name']}",
                module='cisco.ios.ios_config',
                params=[
                    ('parents', f"interface {ifc['name']}"),
                    ('lines', residue),
                ],
            ))

    if users:
        aggregate = []
        for u in users:
            entry: dict = {'name': u['name']}
            if 'privilege' in u:
                entry['privilege'] = u['privilege']
            if 'value' in u:
                # We keep the original (possibly already-hashed) secret as the
                # password value. If hash_type is set it's an already-hashed
                # password; cisco.ios.ios_user can accept pre-hashed values
                # via hashed_password on newer releases.
                if u.get('secret', False) and u.get('hash_type') is not None:
                    entry['hashed_password'] = {
                        'type': u['hash_type'],
                        'value': u['value'],
                    }
                else:
                    entry['configured_password'] = u['value']
            aggregate.append(entry)
        task_list.append(Task(
            name='Configure local user accounts',
            module='cisco.ios.ios_user',
            params=[('aggregate', aggregate), ('state', 'present')],
        ))

    for kind, text in banners:
        task_list.append(Task(
            name=f'Configure {kind} banner',
            module='cisco.ios.ios_banner',
            params=[('banner', kind), ('text', text), ('state', 'present')],
        ))

    if logging_lines:
        task_list.append(Task(
            name='Apply logging configuration',
            module='cisco.ios.ios_config',
            params=[('lines', logging_lines)],
        ))

    if ntp_servers:
        task_list.append(Task(
            name='Configure NTP servers',
            module='cisco.ios.ios_config',
            params=[('lines', [f'ntp server {s}' for s in ntp_servers])],
        ))

    if globals_simple:
        task_list.append(Task(
            name='Apply global configuration',
            module='cisco.ios.ios_config',
            params=[('lines', globals_simple)],
        ))

    # Remaining raw blocks: one task each so the playbook stays readable.
    for header, children in raw_blocks:
        # Strip Cisco's cosmetic bang-comments from the child commands.
        cleaned = [c for c in children if c.strip() != '!']
        if not cleaned:
            continue
        nice = header if len(header) <= 60 else header[:57] + '...'
        task_list.append(Task(
            name=f'Apply block: {nice}',
            module='cisco.ios.ios_config',
            params=[('parents', header), ('lines', cleaned)],
        ))

    rendered: list[str] = list(hdr)
    for t in task_list:
        rendered.extend(render_task(t))
        rendered.append('')  # blank line between tasks
    return '\n'.join(rendered) + '\n'


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

    lines = raw_text.splitlines()
    banners, stripped = extract_banners(lines)
    blocks = parse_blocks(stripped)

    # Peek at hostname (for default --host).
    hostname_hint = None
    for hdr, _ln, _children in blocks:
        if hdr.startswith('hostname '):
            hostname_hint = hdr.split(None, 1)[1].strip()
            break

    host_target = args.host or hostname_hint or 'switches'

    playbook = build_playbook(
        blocks, banners, host=host_target, source_file=args.input,
    )

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
