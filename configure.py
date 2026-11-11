#!/usr/bin/env python3
"""Prepare portable local CLI mappings; preserves existing project checks.

Every agent role gets a pinned model id and an explicit effort, and runs with
``--strict-routing`` (no alias, no fallback, served-model check, routing evidence). Builders are
routed by ticket risk/complexity (builder_routine / builder_complex / builder_critical); critical
tickets may escalate either reviewer lens. Override any role with ``--route ROLE=PROVIDER:MODEL:EFFORT``.
"""
import argparse
import json
from pathlib import Path
import sys

from skill_inventory import builder_skills

EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
CODEX_EFFORTS = ('low', 'medium', 'high')
ROLES = ('builder_routine', 'builder_complex', 'builder_critical', 'reviewer_standards', 'reviewer_spec',
         'reviewer_standards_critical', 'reviewer_spec_critical')
LEGACY_ALIASES = {'frontend': 'builder_routine', 'backend': 'builder_routine', 'critical': 'builder_critical'}


def parse_route(text):
    try:
        role, rest = text.split('=', 1)
        provider, model, effort = rest.split(':')
    except ValueError:
        raise argparse.ArgumentTypeError('--route takes ROLE=PROVIDER:MODEL:EFFORT') from None
    if role not in ROLES:
        raise argparse.ArgumentTypeError(f'unknown role {role!r} (one of {", ".join(ROLES)})')
    if provider not in ('claude', 'codex'):
        raise argparse.ArgumentTypeError('provider must be claude or codex')
    if not model.strip() or any(ch.isspace() for ch in model) or model.startswith('-'):
        raise argparse.ArgumentTypeError('model must be a nonempty explicit model ID')
    if effort not in (CODEX_EFFORTS if provider == 'codex' else EFFORTS):
        raise argparse.ArgumentTypeError(f'effort {effort!r} is not supported for {provider}')
    return role, (provider, model, effort)


def mapping(bridge, skill, role, provider, model, effort):
    mode = 'builder' if role.startswith('builder') else 'reviewer'
    d = {'argv': [sys.executable, str(bridge), '--provider', provider, '--mode', mode, '--model', '{model}',
                  '--effort', effort, '--strict-routing', '--prompt-file', '{prompt_file}',
                  '--result-file', '{result_file}'],
         'stdin_prompt': False, 'model': model, 'effort': effort, 'provider': provider}
    if mode == 'builder':
        d['primary_skill'] = str(skill)
    return d


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--tdd-skill', type=Path)
    p.add_argument('--skills-inventory', type=Path, help='verified Matt/Superpowers skill inventory')
    p.add_argument('--provider', choices=['claude', 'codex'], help='default provider for all roles')
    p.add_argument('--model', help='explicit model ID available in your account')
    p.add_argument('--effort', choices=EFFORTS, default='medium')
    p.add_argument('--egm', action='store_true', help='require approved EGM handoffs for every ticket')
    p.add_argument('--route', action='append', type=parse_route, default=[],
                   help='override one role, e.g. builder_routine=codex:gpt-6.1-sol:medium (repeatable)')
    p.add_argument('--apply', action='store_true')
    a = p.parse_args(argv)
    helpers = {}
    inventory = None
    if a.skills_inventory:
        if a.tdd_skill:
            p.error('Choose --skills-inventory or --tdd-skill, not both')
        try:
            inventory = json.loads(a.skills_inventory.read_text())
            skill, helpers = builder_skills(inventory)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            p.error(str(exc))
    else:
        if not a.tdd_skill:
            p.error('Provide --skills-inventory or --tdd-skill')
        skill = a.tdd_skill.expanduser().resolve()
        if not skill.is_file():
            p.error('--tdd-skill must point to the installed TDD SKILL.md')
    path = a.repo.resolve() / '.infra-factory/config.json'
    c = json.loads(path.read_text())
    bridge = Path(__file__).with_name('agent_bridge.py').resolve()
    if bool(a.provider) != bool(a.model):
        p.error('--provider and --model must be supplied together')
    routes = {}
    if a.provider:
        for role in ROLES:
            try:
                _, route = parse_route(f'{role}={a.provider}:{a.model}:{a.effort}')
            except argparse.ArgumentTypeError as exc:
                p.error(str(exc))
            routes[role] = route
    routes.update(dict(a.route))
    missing = set(ROLES) - set(routes)
    if missing:
        p.error('Choose explicit --provider/--model or --route for every role; missing: ' + ', '.join(sorted(missing)))
    if a.egm:
        c['workflow'] = 'egm'
    commands = {role: mapping(bridge, skill, role, *routes[role]) for role in ROLES}
    for role, spec in commands.items():
        if role.startswith('builder') and helpers:
            spec['support_skills'] = dict(helpers)
    if inventory is not None:
        c['skill_inventory'] = inventory
    else:
        c.pop('skill_inventory', None)
    for legacy, role in LEGACY_ALIASES.items():   # tickets are still validated by role
        commands[legacy] = commands[role]
    c['commands'] = commands
    print(json.dumps(c, indent=2))
    if a.apply:
        # Explicit backup, never silently overwrite an earlier backup.
        backup = path.with_suffix('.json.before-cli-config')
        if backup.exists():
            p.error('Backup already exists; review configuration manually before repeating --apply')
        backup.write_bytes(path.read_bytes())
        path.write_text(json.dumps(c, indent=2) + '\n')
        print('Saved CLI mappings; review project checks and commit only intended factory configuration.',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
