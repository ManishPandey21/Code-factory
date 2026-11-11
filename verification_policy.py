"""Fail-closed specification, impact and test-evidence policy.

The controller owns configuration and runs every selected check in a cold checkout.
It must create a fresh report location before each invocation, bind its resulting
bytes to the candidate/base/configuration, and retain them for independent review.
These validators do not prove that a reporting test runner is honest or that a
specification is semantically complete; those require trusted runners and review.
No exit-code-only command can satisfy the evidence contract.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
import re

from path_safety import checked_path


class PolicyError(ValueError):
    """Missing, ambiguous or failing verification must block readiness."""


DOMAINS = frozenset({'frontend', 'backend', 'shared'})
KINDS = frozenset({'unit', 'integration', 'e2e', 'component', 'visual', 'api',
                   'contract', 'migration', 'security', 'build', 'lint', 'typecheck'})
MINIMUM = {'frontend': {'unit', 'component', 'visual', 'e2e'},
           'backend': {'unit', 'api', 'integration'}, 'shared': {'contract'}}
SECTIONS = ('ui', 'api', 'data', 'cross_cutting')


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value, label):
    if not isinstance(value, list) or not value or not all(_nonempty(x) for x in value):
        raise PolicyError(f'{label} must be a nonempty list of nonempty strings')
    if len(value) != len(set(value)):
        raise PolicyError(f'{label} contains duplicates')
    return value


def _relative(value, label):
    if not _nonempty(value):
        raise PolicyError(f'{label} must be a relative path')
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or '..' in path.parts or
            '\\' in value or any(c in value for c in '*?[:\x00\n\r')):
        raise PolicyError(f'{label} must be a literal relative path without traversal')
    return path.as_posix()


def _intersects(a, b):
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


def validate_spec(ticket):
    """Require explicit scope or justified non-applicability for every layer."""
    _strings(ticket.get('acceptance'), 'ticket acceptance')
    spec = ticket.get('spec')
    if not isinstance(spec, dict) or set(spec) != set(SECTIONS):
        raise PolicyError('spec must contain exactly ui, api, data and cross_cutting sections')
    for name in SECTIONS:
        section = spec[name]
        if not isinstance(section, dict):
            raise PolicyError(f'spec.{name} must be an object')
        if set(section) == {'not_applicable'}:
            if not _nonempty(section['not_applicable']):
                raise PolicyError(f'spec.{name} needs a non-applicability justification')
        elif set(section) == {'impact', 'acceptance'}:
            if not _nonempty(section['impact']):
                raise PolicyError(f'spec.{name}.impact is required')
            _strings(section['acceptance'], f'spec.{name}.acceptance')
        else:
            raise PolicyError(f'spec.{name} must define impact/acceptance or not_applicable, exclusively')
    if all('not_applicable' in spec[name] for name in SECTIONS):
        raise PolicyError('At least one specification section must describe an impact')
    return spec


def validate_policy(config, ticket):
    """Return every check applicable to declared path impact, or fail closed.

    Path roots may overlap: all matching domains count. Unknown or shared paths,
    and declarations encompassing a configured root, conservatively require the
    full stack. Additional required kinds may strengthen, never weaken, minima.
    """
    if not isinstance(config, dict) or not isinstance(ticket, dict):
        raise PolicyError('configuration and ticket must be objects')
    validate_spec(ticket)
    policy = config.get('verification')
    if not isinstance(policy, dict) or set(policy) != {'path_domains', 'checks', 'required'}:
        raise PolicyError('verification must define path_domains, checks and required')
    roots = policy['path_domains']
    if not isinstance(roots, dict) or set(roots) != DOMAINS:
        raise PolicyError('path_domains must define frontend, backend and shared')
    normalized = {}
    for domain, paths in roots.items():
        normalized[domain] = [_relative(p, f'{domain} root') for p in _strings(paths, f'{domain} roots')]
        if len(normalized[domain]) != len(set(normalized[domain])):
            raise PolicyError(f'{domain} roots contain normalized duplicates')
    required = policy['required']
    if not isinstance(required, dict) or set(required) - DOMAINS:
        raise PolicyError('required must map known domains to test kinds')
    for domain, kinds in required.items():
        if set(_strings(kinds, f'{domain} required kinds')) - KINDS:
            raise PolicyError(f'{domain} has an unknown required kind')
    impacted = set()
    for path in _strings(ticket.get('paths'), 'ticket paths'):
        path = _relative(path, 'ticket path')
        matches = {d for d, paths in normalized.items() if any(_intersects(path, p) for p in paths)}
        impacted |= matches or DOMAINS
    if 'shared' in impacted or {'frontend', 'backend'} <= impacted:
        impacted = set(DOMAINS)
    checks = policy['checks']
    if not isinstance(checks, list) or not checks:
        raise PolicyError('verification checks must be a nonempty list')
    ids, reports, selected = set(), set(), []
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'id', 'domains', 'kind', 'argv', 'report', 'min_tests'}:
            raise PolicyError('Each check requires id, domains, kind, argv, report and min_tests')
        cid = check['id']
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', cid) or cid in ids:
            raise PolicyError('Check ids must be unique safe identifiers')
        ids.add(cid)
        domains = set(_strings(check['domains'], f'{cid} domains'))
        if domains - DOMAINS or not isinstance(check['kind'], str) or check['kind'] not in KINDS:
            raise PolicyError(f'{cid} has unknown domains or kind')
        argv = check['argv']
        if not isinstance(argv, list) or not argv or not all(_nonempty(a) and '\x00' not in a for a in argv):
            raise PolicyError(f'{cid} needs a nonempty argv array')
        report = _relative(check['report'], f'{cid} report')
        if any(p.lower() in {'.git', '.infra-factory', '.github', '.claude', '.codex', '.agents'}
               for p in PurePosixPath(report).parts):
            raise PolicyError('Report may not target control or policy directories')
        if report in reports:
            raise PolicyError('Checks may not share report paths')
        reports.add(report)
        if type(check['min_tests']) is not int or check['min_tests'] < 1:
            raise PolicyError(f'{cid} min_tests must be a positive integer')
        if domains & impacted:
            selected.append(dict(check))
    for domain in impacted:
        kinds = {x['kind'] for x in selected if domain in x['domains']}
        missing = (MINIMUM[domain] | set(required.get(domain, []))) - kinds
        if missing:
            raise PolicyError(f'Missing required {domain} check kinds: {", ".join(sorted(missing))}')
    return selected


def validate_evidence(report_path, check):
    """Validate aggregate counts from a controller-selected, freshly written report.

    Report JSON is exactly status/total/passed/failed/skipped. A skipped, empty,
    inconsistent, malformed or symlinked report never counts as verification.
    The caller must ensure a unique path or remove stale output before execution.
    """
    try:
        path = checked_path(report_path)
    except ValueError as exc:
        raise PolicyError(str(exc)) from exc
    if not path.is_file():
        raise PolicyError('Evidence report is missing or is not a regular file')
    if path.stat().st_size > 1024 * 1024:
        raise PolicyError('Evidence report exceeds 1 MiB')
    try:
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise PolicyError(f'Duplicate evidence key: {key}')
                obj[key] = value
            return obj
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f'Cannot read evidence: {exc}') from exc
    if not isinstance(data, dict) or set(data) != {'status', 'total', 'passed', 'failed', 'skipped'}:
        raise PolicyError('Malformed evidence schema')
    if any(type(data[key]) is not int or data[key] < 0 for key in ('total', 'passed', 'failed', 'skipped')):
        raise PolicyError('Evidence counts must be nonnegative integers')
    minimum = check.get('min_tests')
    if type(minimum) is not int or minimum < 1:
        raise PolicyError('Check has no valid minimum test count')
    if (data['status'] != 'passed' or data['total'] < minimum or
            data['passed'] != data['total'] or data['failed'] != 0 or data['skipped'] != 0):
        raise PolicyError('Evidence contains failed, skipped, empty or insufficient tests')
    return data
