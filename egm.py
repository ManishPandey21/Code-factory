#!/usr/bin/env python3
"""Bind an EGM-reviewed, human-approved design to a factory ticket.

This imports an operator attestation, not proof of reviewer independence or a
human identity. Run native EGM review first; never manufacture approval.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

from path_safety import checked_path

STAGES = ('initial_zoom_out', 'comprehension', 'design_critique',
          'intermediate_zoom_out', 'implementation_readiness')
UPSTREAM = 'https://github.com/google/elephant-goldfish-model'
REFERENCE_COMMIT = '0f06dd7230261c00f0e03bd8d3ca8b5a1b898e2b'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ticket_digest(ticket):
    return digest(json.dumps({k: v for k, v in ticket.items() if k != 'egm'},
                             sort_keys=True, separators=(',', ':')).encode(encoding='utf-8'))


def artifact(repo, path):
    """Only unchanged, committed local files may be design handoff inputs."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError('EGM artifact path must be a nonempty string')
    rel = PurePosixPath(path)
    if (rel.is_absolute() or '..' in rel.parts or not rel.parts or
            any(c in path for c in '\\:\x00\n\r') or rel.as_posix() != path):
        raise ValueError('EGM artifacts must use normalized relative paths')
    if any(part in {'.git', '.infra-factory'} for part in rel.parts):
        raise ValueError('EGM artifacts must be project documents')
    repo = Path(repo).resolve()
    target = checked_path(repo / path, root=repo)
    if not target.is_file():
        raise ValueError('EGM artifact must be a regular file without symlinks: ' + path)
    raw = target.read_bytes()
    if not raw.strip():
        raise ValueError('Empty EGM artifact: ' + path)
    committed = subprocess.run(['git', '-C', str(repo), 'show', 'HEAD:' + path],
                               capture_output=True, timeout=30)
    if committed.returncode or committed.stdout != raw:
        raise ValueError('Commit the EGM artifact before handoff: ' + path)
    return {'path': path, 'sha256': digest(raw)}


def validate_handoff(repo, ticket, required=False):
    receipt = ticket.get('egm')
    if receipt is None and not required:
        return
    if not isinstance(receipt, dict) or receipt.get('schema') != 1:
        raise ValueError('EGM workflow requires a version 1 handoff')
    if receipt.get('ticket_sha256') != ticket_digest(ticket):
        raise ValueError('EGM handoff does not match ticket; review changed scope again')
    approval = receipt.get('approval')
    if not isinstance(approval, dict) or any(not isinstance(approval.get(k), str) or
            not approval[k].strip() for k in ('by', 'note')):
        raise ValueError('EGM handoff requires recorded human approval and disposition of findings')
    reports = receipt.get('reports')
    if not isinstance(reports, dict) or set(reports) != set(STAGES):
        raise ValueError('EGM handoff requires all five design-review stage reports')
    for entry in [receipt.get('design'), *reports.values()]:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}:
            raise ValueError('Malformed EGM artifact reference')
        if artifact(repo, entry['path']) != entry:
            raise ValueError('EGM artifact changed since approval: ' + entry['path'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--ticket', required=True, type=Path)
    p.add_argument('--design', required=True, help='committed project-relative design path')
    p.add_argument('--report', action='append', required=True, metavar='STAGE=PATH')
    p.add_argument('--approved-by', required=True, help='actual human approval attribution')
    p.add_argument('--approval-note', required=True, help='approval reference and disposition of findings')
    p.add_argument('--output', required=True, type=Path, help='new ticket file; never overwritten')
    a = p.parse_args(argv)
    from factory import FactoryError, validate_ticket
    try:
        ticket = validate_ticket(json.loads(a.ticket.read_text(encoding='utf-8')))
    except FactoryError as exc:
        raise ValueError(str(exc)) from exc
    reports = {}
    for item in a.report:
        stage, sep, path = item.partition('=')
        if not sep or stage not in STAGES or stage in reports:
            p.error('--report requires each of these stages exactly once: ' + ', '.join(STAGES))
        reports[stage] = artifact(a.repo, path)
    ticket['egm'] = {'schema': 1, 'ticket_sha256': ticket_digest(ticket),
                     'design': artifact(a.repo, a.design), 'reports': reports,
                     'approval': {'by': a.approved_by, 'note': a.approval_note}}
    validate_handoff(a.repo, ticket, required=True)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(ticket, stream, indent=2)
        stream.write('\n')
    print('Saved EGM-bound ticket: ' + str(a.output))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('egm: ' + str(exc), file=sys.stderr)
        sys.exit(2)
