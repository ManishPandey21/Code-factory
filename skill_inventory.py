#!/usr/bin/env python3
"""Discover selected installed skills without copying sources or executing them."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

CATALOG = {
    'matt': ('setup-matt-pocock-skills', 'grill-with-docs', 'to-tickets', 'domain-modeling',
             'codebase-design', 'code-review', 'research', 'prototype', 'diagnosing-bugs',
             'tdd', 'improve-codebase-architecture', 'retro', 'handoff'),
    'superpowers': ('test-driven-development', 'systematic-debugging',
                   'verification-before-completion', 'receiving-code-review', 'requesting-code-review'),
}
REQUIRED = tuple('superpowers:' + name for name in CATALOG['superpowers'][:3])
BUILDER_HELPERS = {
    'debugging': 'superpowers:systematic-debugging',
    'verification': 'superpowers:verification-before-completion',
    'feedback': 'superpowers:receiving-code-review',
    'design': 'matt:codebase-design',
}


def metadata(path):
    text = path.read_text(encoding='utf-8')
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
    if not match:
        raise ValueError(f'Skill has no YAML frontmatter: {path}')
    # Deliberately support only simple, unquoted top-level YAML keys. Unknown
    # syntax (quoted/escaped keys, aliases or merges) must never hide an invocation
    # restriction. Indented scalar/list continuations are left uninterpreted.
    seen = set()
    for line in match[1].splitlines():
        if not line.strip() or line[0].isspace() or line.startswith('#'):
            continue
        key = re.match(r'([A-Za-z][A-Za-z0-9_-]*):', line)
        if not key or key[1] in seen:
            raise ValueError(f'Unsupported or duplicate frontmatter key: {path}')
        seen.add(key[1])
    name = re.search(r'^name:\s*[\'"]?([a-z0-9-]+)[\'"]?\s*$', match[1], re.M)
    if not name:
        raise ValueError(f'Skill has no plain name: {path}')
    flag = re.search(r'^disable-model-invocation:\s*(.*?)\s*$', match[1], re.M)
    if flag and flag[1] not in ('true', 'false'):
        raise ValueError(f'Unsupported invocation flag: {path}')
    return name[1], bool(flag and flag[1] == 'true')


def skill_files(path):
    """Hash the complete skill directory, including helper scripts and references."""
    path = Path(path)
    if not path.is_absolute() or path.name != 'SKILL.md' or not path.is_file():
        raise ValueError('Skill must be an existing absolute SKILL.md path')
    root = path.parent
    files = {}
    for entry in sorted(root.rglob('*')):
        if entry.is_symlink():
            raise ValueError(f'Skill directory contains a symlink: {entry}')
        if entry.is_file():
            files[str(entry)] = hashlib.sha256(entry.read_bytes()).hexdigest()
    return files


def discover(roots):
    entries = {}
    for provider, names in CATALOG.items():
        root = roots.get(provider)
        for name in names:
            key = provider + ':' + name
            paths = []
            if root is not None:
                root = Path(root).expanduser().resolve(strict=True)
                for prefix in ('skills/engineering', 'skills/productivity', 'skills', ''):
                    path = root / prefix / name / 'SKILL.md'
                    if path.is_file():
                        paths.append(path.resolve())
            paths = sorted(set(paths))
            if len(paths) > 1:
                raise ValueError(f'Ambiguous installed skill {key}; select a narrower root')
            if not paths:
                entries[key] = {'available': False}
                continue
            path = paths[0]
            actual, user_only = metadata(path)
            if actual != name:
                raise ValueError(f'Skill name mismatch: {path}')
            entries[key] = {'available': True, 'path': str(path), 'user_invoked_only': user_only,
                            'files': skill_files(path)}
    return {'version': 1, 'skills': entries}


def validate_inventory(data):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('skills'), dict):
        raise ValueError('Invalid skill inventory')
    for key, entry in data['skills'].items():
        if not isinstance(entry, dict) or type(entry.get('available')) is not bool:
            raise ValueError('Invalid skill inventory entry: ' + key)
        if not entry['available']:
            continue
        name, user_only = metadata(Path(entry['path']))
        if key.split(':', 1)[-1] != name or entry.get('user_invoked_only') is not user_only:
            raise ValueError('Skill metadata changed; regenerate inventory: ' + key)
        if skill_files(entry['path']) != entry.get('files'):
            raise ValueError('Skill content changed; regenerate inventory: ' + key)
    return data


def builder_skills(data):
    validate_inventory(data)
    for key in REQUIRED:
        entry = data['skills'].get(key, {})
        if not entry.get('available') or entry.get('user_invoked_only'):
            raise ValueError('Required model-invocable skill unavailable: ' + key)
    helpers = {}
    for stage, key in BUILDER_HELPERS.items():
        entry = data['skills'].get(key, {})
        if entry.get('available') and not entry.get('user_invoked_only'):
            helpers[stage] = entry['path']
    return data['skills'][REQUIRED[0]]['path'], helpers


def helper_prompt(spec):
    helpers = spec.get('support_skills', {})
    if not isinstance(helpers, dict) or set(helpers) - set(BUILDER_HELPERS):
        raise ValueError('Unknown builder support skill stage')
    triggers = {'debugging': 'Only after a failing check or unexpected behavior, diagnose before fixing',
                'verification': 'Before claiming completion, gather fresh command evidence',
                'feedback': 'Only when prior review feedback exists, evaluate it before making changes',
                'design': 'Only when changing module boundaries, use the deep-module design guidance'}
    lines = []
    for stage, path in helpers.items():
        _, user_only = metadata(Path(path))
        skill_files(path)
        if user_only:
            raise ValueError('User-invoked skill cannot be loaded automatically by a builder: ' + path)
        lines.append(triggers[stage] + ': read ' + path)
    if not lines:
        return ''
    return ('\nConditional skill support (do not load all skills at startup):\n' + '\n'.join(lines) +
            '\nKeep one active primary discipline. Preserve existing code and follow referenced helpers. '
            'The factory owns allocation, worktrees, commits and publication; do not start another '
            'orchestrator, spawn agents, merge, deploy, or delete unrelated work.\n')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matt-root', type=Path)
    p.add_argument('--superpowers-root', type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args(argv)
    data = discover({'matt': a.matt_root, 'superpowers': a.superpowers_root})
    builder_skills(data)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2); stream.write('\n')
    print('Saved verified skill inventory: ' + str(a.output))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('skill_inventory: ' + str(exc), file=sys.stderr)
        sys.exit(2)
