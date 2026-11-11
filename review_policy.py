"""Project-owned specialist selection and candidate risk/approval contracts."""
import fnmatch
import hashlib
import json
from pathlib import Path
import re

LEVELS = ('low', 'medium', 'high', 'critical')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def patterns(value):
    if not isinstance(value, list) or not value or any(
            not isinstance(x, str) or not x or x.startswith('/') or '\\' in x or
            '..' in x.split('/') or any(ord(c) < 32 for c in x) for x in value):
        raise ValueError('Review paths must be nonempty repository-relative glob patterns')
    return value


def matches(files, globs):
    return any(fnmatch.fnmatchcase(path, glob) for path in files for glob in globs)


def validate(policy):
    if not isinstance(policy, dict) or set(policy) - {'specialists', 'risk'}:
        raise ValueError('review_policy supports specialists and risk')
    specialists = policy.get('specialists', {})
    if not isinstance(specialists, dict) or len(specialists) > 8:
        raise ValueError('At most eight specialist lenses are supported')
    for name, rule in specialists.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', name) or name in {'standards', 'spec', 'risk'}:
            raise ValueError('Invalid or reserved specialist name')
        if not isinstance(rule, dict) or set(rule) != {'paths', 'focus'}:
            raise ValueError('Specialist requires paths and focus')
        patterns(rule['paths'])
        if not isinstance(rule['focus'], str) or not rule['focus'].strip():
            raise ValueError('Specialist focus must be nonempty')
    risk = policy.get('risk')
    if risk is not None:
        if not isinstance(risk, dict) or set(risk) != {'minimum_level', 'human_review_levels', 'path_levels'}:
            raise ValueError('Risk requires minimum_level, human_review_levels and path_levels')
        if risk['minimum_level'] not in LEVELS:
            raise ValueError('Invalid minimum risk level')
        if (not isinstance(risk['human_review_levels'], list) or not risk['human_review_levels'] or
                any(x not in LEVELS for x in risk['human_review_levels'])):
            raise ValueError('Risk human_review_levels must be a nonempty list of risk levels')
        # Threshold must be monotonic: a higher risk can never bypass a lower gate.
        first = min(LEVELS.index(x) for x in risk['human_review_levels'])
        if set(risk['human_review_levels']) != set(LEVELS[first:]):
            raise ValueError('Human review levels must include all levels above their threshold')
        if not isinstance(risk['path_levels'], list):
            raise ValueError('Risk path_levels must be a list')
        for rule in risk['path_levels']:
            if not isinstance(rule, dict) or set(rule) != {'paths', 'level'} or rule['level'] not in LEVELS:
                raise ValueError('Risk path rule requires paths and level')
            patterns(rule['paths'])
    return policy


def required_commands(policy):
    validate(policy)
    return ['reviewer_' + name for name in policy.get('specialists', {})] + (
        ['risk_assessor'] if policy.get('risk') is not None else [])


def lenses(policy, files):
    validate(policy)
    return ['standards', 'spec'] + [name for name, rule in policy.get('specialists', {}).items()
                                    if matches(files, rule['paths'])]


def assess(policy, assessment, files, head, base, critical=False):
    """Combine independent assessment with policy floors; agents cannot lower them."""
    validate(policy)
    risk = policy['risk']
    if (not isinstance(assessment, dict) or assessment.get('reviewed_head') != head or
            assessment.get('base') != base or assessment.get('level') not in LEVELS or
            not isinstance(assessment.get('rationale'), str) or not assessment['rationale'].strip() or
            not isinstance(assessment.get('covered_files'), list) or
            sorted(assessment['covered_files']) != sorted(files) or
            type(assessment.get('requires_human', False)) is not bool):
        raise ValueError('Risk assessment must cover the exact candidate/base and all changed files')
    levels = [risk['minimum_level'], assessment['level']]
    levels += [r['level'] for r in risk['path_levels'] if matches(files, r['paths'])]
    if critical:
        levels.append('critical')
    level = max(levels, key=LEVELS.index)
    return {'level': level, 'requires_human': assessment.get('requires_human', False) or
            level in risk['human_review_levels'], 'assessment': assessment,
            'head': head, 'base': base, 'policy': digest(policy)}


def check_risk(record, policy, files, head, base, critical=False):
    if not isinstance(record, dict):
        raise ValueError('Independent risk evidence is missing')
    data = dict(record)
    signature = data.pop('digest', None)
    if signature != digest(data):
        raise ValueError('Risk evidence digest mismatch')
    expected = assess(policy, record.get('assessment'), files, head, base, critical)
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError('Risk evidence policy or candidate mismatch')
    artifact = record.get('artifact', {})
    path = Path(artifact.get('file', ''))
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get('sha256'):
        raise ValueError('Risk assessment artifact missing or changed')
    if json.loads(path.read_text()) != record['assessment']:
        raise ValueError('Risk assessment differs from its recorded artifact')
    return record


def approved(review, head, policy_hash):
    risk = review.get('risk')
    if not risk or not risk['requires_human']:
        return True
    approval = review.get('human_approval', {})
    return (approval.get('head') == head and approval.get('risk_digest') == risk['digest'] and
            approval.get('policy') == policy_hash and
            all(isinstance(approval.get(k), str) and approval[k].strip() for k in ('reviewer', 'note')))
