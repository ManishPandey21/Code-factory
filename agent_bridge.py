#!/usr/bin/env python3
"""Normalize final review JSON from local authenticated Claude/Codex CLIs.

No embedded credentials, SDK, provider API or permission bypass. Reviewer runs
receive a disposable home/config/cache and only provider authentication material,
never user settings, plugins, history or memory. This is context hygiene, not an
OS security boundary: same-user processes can still access host files. Desktop
keychain authentication (especially Claude on macOS) may not work in this profile;
run a live authenticated pilot before adoption. Only fake-CLI tests have run here.

0.3.4 strict routing (``--strict-routing``, written by configurations that pin models): the
requested model must be a full model id (no alias another variable could remap), ``--effort`` is
required and validated (the Claude CLI itself accepts unknown effort names silently), the effort is
passed both as ``--effort`` and as ``CLAUDE_CODE_EFFORT_LEVEL`` (which the CLI lets override the
flag), model fallback is disabled, a settings ``maxEffortLevel`` below the request refuses the run
instead of being clamped silently, the model that actually served the run must be the requested
one, and a routing evidence file records what was requested and what happened (never credentials).
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')   # Claude Code CLI `--effort` levels, in order
CODEX_EFFORTS = ('low', 'medium', 'high')             # Codex model_reasoning_effort values used here
FULL_CLAUDE_ID = re.compile(r'claude-(?:[a-z]+(?:-[0-9]+)+|[0-9]+(?:-[0-9]+)*-[a-z]+-[0-9]{8})')
# Variables that could change which model or effort a strict run uses. They are removed (or, for
# the effort level, set explicitly) so the requested pair is the effective one.
MODEL_OVERRIDES = ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
                   'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL',
                   'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_EFFORT')


class RoutingError(ValueError):
    """The requested model/effort cannot be honoured exactly; the run must not proceed."""


def settings_files(cwd, env):
    """Settings files the Claude CLI reads for this run, most general first."""
    config = Path(env.get('CLAUDE_CONFIG_DIR') or Path(env.get('HOME', str(Path.home()))) / '.claude')
    files = [Path('/etc/claude-code/managed-settings.json'),
             Path('/Library/Application Support/ClaudeCode/managed-settings.json'),
             config / 'settings.json', cwd / '.claude' / 'settings.json', cwd / '.claude' / 'settings.local.json']
    return [f for f in files if f.is_file()]


def effort_caps(cwd, env):
    caps = []
    for f in settings_files(cwd, env):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise RoutingError(f'cannot read Claude settings file {f} to check effort caps')
        if isinstance(data, dict) and data.get('maxEffortLevel') is not None:
            caps.append({'file': str(f), 'maxEffortLevel': data['maxEffortLevel']})
    return caps


def strict_claude_env(base, effort):
    env = dict(os.environ if base is None else base)
    removed = sorted(k for k in MODEL_OVERRIDES if k in env)
    for key in removed:
        del env[key]
    env['CLAUDE_CODE_EFFORT_LEVEL'] = effort      # the CLI lets this override --effort: make them equal
    env['CLAUDE_CODE_NO_MODEL_FALLBACK'] = '1'
    return env, removed


def served_models(envelope):
    usage = envelope.get('modelUsage')
    if not isinstance(usage, dict):
        return {}
    keep = ('inputTokens', 'outputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens', 'costUSD')
    return {str(m): {k: v.get(k) for k in keep if isinstance(v, dict) and k in v} for m, v in usage.items()}


def check_served(requested, served):
    if requested not in served:
        raise RoutingError(f'requested model {requested} did not serve this run (served: {sorted(served) or "none"}); '
                           'refusing a substituted or fallback model')
    mine = served[requested].get('outputTokens') or 0
    for model, usage in served.items():
        if model != requested and (usage.get('outputTokens') or 0) > mine:
            raise RoutingError(f'model {model} produced more output than the requested {requested}; '
                               'treating it as a silent substitution')


def write_evidence(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(data, indent=2, sort_keys=True) + '\n')


@contextlib.contextmanager
def reviewer_environment(provider):
    """Keep the entire CLI lifetime inside a new, nonpersistent user profile."""
    platform_keys = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
                     'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ'}
    # Network reachability is host configuration, not builder context: without
    # these a reviewer behind a corporate proxy/private CA cannot reach its provider.
    platform_keys |= {k for k in os.environ if k.upper() in {
        'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'ALL_PROXY', 'SSL_CERT_FILE',
        'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS', 'REQUESTS_CA_BUNDLE'}}
    auth_keys = ({'OPENAI_API_KEY', 'CODEX_API_KEY'} if provider == 'codex'
                 else {'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'})
    env = {key: value for key, value in os.environ.items()
           if key in platform_keys | auth_keys}
    source_home = Path.home()
    source_config = Path(os.environ.get(
        'CODEX_HOME' if provider == 'codex' else 'CLAUDE_CONFIG_DIR',
        str(source_home / ('.codex' if provider == 'codex' else '.claude'))))
    with tempfile.TemporaryDirectory(prefix='infra-cold-profile-') as tmp:
        home = Path(tmp)
        paths = {'HOME': home, 'USERPROFILE': home,
                 'CODEX_HOME': home / '.codex', 'CLAUDE_CONFIG_DIR': home / '.claude',
                 'XDG_CONFIG_HOME': home / '.config', 'XDG_CACHE_HOME': home / '.cache',
                 'XDG_STATE_HOME': home / '.state', 'XDG_DATA_HOME': home / '.local/share',
                 'TMP': home / 'tmp', 'TEMP': home / 'tmp', 'TMPDIR': home / 'tmp'}
        for key, path in paths.items():
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            env[key] = str(path)
        credential_name = 'auth.json' if provider == 'codex' else '.credentials.json'
        source = source_config / credential_name
        if source.is_symlink():
            raise ValueError('Reviewer credential file must not be a symlink')
        copied = target = None
        if source.exists():
            if not source.is_file():
                raise ValueError('Reviewer credential path must be a regular file')
            target = paths['CODEX_HOME' if provider == 'codex' else 'CLAUDE_CONFIG_DIR'] / credential_name
            copied = source.read_bytes()
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(copied)
        try:
            yield env
        finally:
            if copied is not None:
                persist_refreshed_credential(source, target, copied)


def persist_refreshed_credential(source, target, copied):
    """Do not strand a rotated login in the disposable profile.

    OAuth refresh tokens are single-use. If the CLI refreshed inside the temporary
    profile and that file were simply deleted, the owner's real login would hold a
    spent refresh token and be signed out later. Write the refreshed file back, but
    only when the original is byte-identical to what was copied; otherwise another
    session refreshed concurrently and overwriting would discard the newer login.
    """
    try:
        if target.is_symlink() or not target.is_file():
            return
        refreshed = target.read_bytes()
        if refreshed == copied:
            return
        if not isinstance(json.loads(refreshed.decode('utf-8')), dict):
            raise ValueError('refreshed credential is not a JSON object')
        if source.is_symlink() or not source.is_file() or source.read_bytes() != copied:
            print('agent_bridge: WARNING: the reviewer CLI refreshed its login while the original credential '
                  'file also changed; nothing was overwritten. If a CLI later reports an expired or reused '
                  'token, sign in again. Use a dedicated reviewer token to avoid this.', file=sys.stderr)
            return
        staging = source.with_name(source.name + '.factory-refresh-' + str(os.getpid()))
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(refreshed)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staging, source)
        finally:
            if staging.exists():
                staging.unlink()
    except (OSError, ValueError) as exc:
        print('agent_bridge: WARNING: could not persist a refreshed reviewer credential: ' + str(exc), file=sys.stderr)


def parse_review(text):
    text = text.strip()
    if text.startswith('```'):
        parts = text.splitlines()
        if len(parts) < 3 or parts[-1].strip() != '```':
            raise ValueError('Incomplete fenced review JSON')
        text = '\n'.join(parts[1:-1])
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('Review result must be a JSON object')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider', required=True, choices=['claude', 'codex'])
    p.add_argument('--mode', required=True, choices=['builder', 'reviewer'])
    p.add_argument('--model', required=True)
    p.add_argument('--prompt-file', required=True, type=Path)
    p.add_argument('--result-file', required=True, type=Path)
    p.add_argument('--effort', choices=EFFORTS, help='reasoning effort (required with --strict-routing)')
    p.add_argument('--strict-routing', action='store_true',
                   help='pinned model id + explicit effort, no fallback, served-model check, routing evidence')
    p.add_argument('--evidence-file', type=Path,
                   help='routing evidence path (default: <result-file stem>.routing.json beside it)')
    a = p.parse_args()
    if a.result_file.exists() or a.result_file.is_symlink():
        raise ValueError('Result path already exists; stale evidence cannot be reused')
    if not a.strict_routing:
        return run(a, None)
    evidence_path = a.evidence_file or a.result_file.with_name(a.result_file.stem + '.routing.json')
    if evidence_path.exists() or evidence_path.is_symlink():
        raise ValueError('Routing evidence path already exists; stale evidence cannot be reused')
    evidence = {'schema': 1, 'provider': a.provider, 'mode': a.mode, 'requested_model': a.model,
                'requested_effort': a.effort, 'started_at': time.time(), 'outcome': 'error'}
    try:
        if a.effort is None:
            raise RoutingError('--strict-routing requires --effort')
        if a.provider == 'claude' and not FULL_CLAUDE_ID.fullmatch(a.model):
            raise RoutingError(f'model {a.model!r} is not a full Claude model id; aliases can be remapped')
        if a.provider == 'codex' and a.effort not in CODEX_EFFORTS:
            raise RoutingError(f'effort {a.effort!r} is not supported for codex ({", ".join(CODEX_EFFORTS)})')
        code = run(a, evidence)
        evidence['exit_code'] = code
        evidence['outcome'] = 'ok' if code == 0 else 'cli_failed'
        return code
    except (OSError, ValueError) as exc:
        evidence['outcome'] = 'routing_refused' if isinstance(exc, RoutingError) else 'error'
        evidence['error'] = str(exc)
        raise
    finally:
        evidence['finished_at'] = time.time()
        write_evidence(evidence_path, evidence)


def run(a, evidence):
    """One agent run. ``evidence`` is None for legacy (non-strict) configurations."""
    if a.prompt_file.is_symlink() or not a.prompt_file.is_file():
        raise ValueError('Prompt must be a regular file, not a symlink')
    prompt_bytes = a.prompt_file.read_bytes()
    prompt = prompt_bytes.decode('utf-8')
    if a.mode == 'reviewer':
        prompt += ('\nTransport override: do not write a result file yourself. Return ONLY the required JSON object '
                   'as your final answer; the local adapter will save it at the designated result path. '
                   'Do not mutate repository files or spawn agents.')
    profile = reviewer_environment(a.provider) if a.mode == 'reviewer' else contextlib.nullcontext(None)
    with profile as env:
        if a.provider == 'codex':
            with tempfile.TemporaryDirectory(prefix='infra-final-') as tmp:
                final = Path(tmp)/'final.txt'
                args = ['codex', 'exec', '--ephemeral', '--model', a.model, '--sandbox',
                        'read-only' if a.mode == 'reviewer' else 'workspace-write',
                        '--output-last-message', str(final), '-']
                if evidence is not None:
                    args[2:2] = ['-c', f'model_reasoning_effort="{a.effort}"']
                    evidence['effort_controls'] = {'codex_config': f'model_reasoning_effort={a.effort}'}
                    # Codex reports no per-run model usage here; the requested pair is recorded as is.
                    evidence['served_models_verified'] = False
                result = subprocess.run(args, input=prompt, text=True, env=env, encoding='utf-8')
                if result.returncode:
                    return result.returncode
                if final.is_symlink():
                    raise ValueError('CLI result must not be a symlink')
                output = final.read_text(encoding='utf-8')
        else:
            args = ['claude', '-p', '--no-session-persistence', '--model', a.model, '--output-format', 'json',
                    '--permission-mode', 'plan' if a.mode == 'reviewer' else 'acceptEdits']
            transcript = None
            envelope = None
            if evidence is not None:
                env, removed = strict_claude_env(env, a.effort)
                caps = effort_caps(Path.cwd(), env)
                evidence['effort_controls'] = {'flag': a.effort, 'CLAUDE_CODE_EFFORT_LEVEL': a.effort,
                                               'CLAUDE_CODE_NO_MODEL_FALLBACK': '1', 'removed_overrides': removed}
                evidence['settings_effort_caps'] = caps
                for cap in caps:
                    level = cap['maxEffortLevel']
                    if level not in EFFORTS or EFFORTS.index(level) < EFFORTS.index(a.effort):
                        raise RoutingError(f'{cap["file"]} sets maxEffortLevel={level!r}, which would silently '
                                           f'clamp the requested effort {a.effort!r}')
                args += ['--effort', a.effort]
                if a.mode == 'builder':
                    # Keep the builder's full transcript as evidence (stream-json needs --verbose).
                    args[args.index('json')] = 'stream-json'
                    args.append('--verbose')
                    transcript = a.result_file.with_name(a.result_file.stem + '.transcript.jsonl')
            # Permission modes retain host/tool restrictions; no bypass flags. Never --fallback-model.
            result = subprocess.run(args, input=prompt, text=True, stdout=subprocess.PIPE, env=env, encoding='utf-8')
            if transcript is not None:
                fd = os.open(transcript, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(result.stdout)
                evidence['transcript'] = str(transcript)
                for line in reversed(result.stdout.splitlines()):
                    with contextlib.suppress(ValueError):
                        item = json.loads(line)
                        if isinstance(item, dict) and item.get('type') == 'result':
                            envelope = item
                            break
                if envelope is None and not result.returncode:
                    raise ValueError('Claude stream ended without a result message')
            elif not result.returncode:
                envelope = json.loads(result.stdout)
            elif evidence is not None:
                with contextlib.suppress(ValueError):   # best effort: record what a failed run reported
                    envelope = json.loads(result.stdout)
            if evidence is not None and isinstance(envelope, dict):
                served = served_models(envelope)
                evidence['served_models'] = served
                for key in ('duration_ms', 'num_turns', 'total_cost_usd', 'is_error', 'stop_reason'):
                    if key in envelope:
                        evidence[key] = envelope[key]
                denials = envelope.get('permission_denials')
                if isinstance(denials, list):
                    evidence['permission_denials'] = [str(d.get('tool_name')) for d in denials if isinstance(d, dict)]
            if result.returncode:
                return result.returncode
            if not isinstance(envelope, dict) or envelope.get('is_error'):
                raise ValueError('Claude returned an error or unsupported envelope')
            if evidence is not None:
                check_served(a.model, evidence['served_models'])
                evidence['served_models_verified'] = True
            output = envelope.get('result')
            if not isinstance(output, str):
                raise ValueError('Claude did not return a textual final result')
    if a.prompt_file.is_symlink() or a.prompt_file.read_bytes() != prompt_bytes:
        raise ValueError('Prompt changed during agent execution')
    data = parse_review(output) if a.mode == 'reviewer' else {'summary': output}
    # Exclusive creation also catches a result planted while the CLI was running.
    fd = os.open(a.result_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(data, indent=2)+'\n')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print('agent_bridge: '+str(exc), file=sys.stderr)
        sys.exit(2)
