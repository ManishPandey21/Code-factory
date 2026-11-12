"""Shared configuration, Git boundaries and owned process lifecycle."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import socket
import subprocess
import threading
import review_policy
from skill_inventory import validate_inventory


CLI_SLOTS = threading.BoundedSemaphore(2)


VERIFY_LOCK = threading.Lock()


GIT_LOCK = threading.Lock()  # worktree add and branch commits share one Git dir


ACTIVE = set()            # child processes owned by this controller


STOP = threading.Event()  # set by SIGINT/SIGTERM; no further commands start


class FactoryError(Exception):
    pass


class TransientError(FactoryError):
    """A remote/transport command failed; local verification evidence is unaffected."""


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=60)
    if p.returncode:
        raise FactoryError(p.stderr.decode(errors='replace').strip())
    return p.stdout.decode(errors='surrogateescape').strip()


def locations(repo):
    repo = Path(git(Path(repo).resolve(), 'rev-parse', '--show-toplevel'))
    common = Path(git(repo, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute():
        common = repo / common
    return repo, common.resolve() / 'infra-factory'


def default_config(repo):
    branch = git(repo, 'symbolic-ref', '--short', 'HEAD')
    codex = {'argv': ['codex', 'exec', '-'], 'stdin_prompt': True, 'model': '', 'primary_skill': ''}
    claude = {'argv': ['claude', '-p'], 'stdin_prompt': True, 'model': '', 'primary_skill': ''}
    return {'version': 1, 'base_ref': branch, 'max_parallel': 2,
            'timeout_seconds': 1800, 'checks': [], 'verification': {},
            'commands': {'backend': codex, 'frontend': claude,
                         'critical': codex, 'reviewer': claude}}


def config_hash(c):
    return hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()


def alive(pid):
    """True unless the local process is positively known to be gone."""
    try:
        pid = int(pid)
    except (ValueError, TypeError):
        return True
    if pid <= 0:
        return True
    if os.name == 'nt':
        # os.kill(pid, 0) on Windows calls TerminateProcess: it would KILL the
        # process being probed. Query it instead. (Not exercised on Windows here.)
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such process
        try:
            code = wintypes.DWORD()
            return not k32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextlib.contextmanager
def lock(home, filename='coordinator.lock'):
    target = home / filename
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise FactoryError(f'{filename} exists; no automatic lock stealing. After verifying its owner exited, use '
                           'recover --ticket ID for a stale RUNNING/REVIEWING ticket, or unlock when no ticket is in flight.')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump({'pid': os.getpid(), 'host': socket.gethostname()}, f)
            f.flush()
            os.fsync(f.fileno())
        yield
    finally:
        target.unlink(missing_ok=True)


def config(repo):
    c = json.loads((repo / '.infra-factory/config.json').read_text())
    if not isinstance(c, dict) or c.get('version') != 1 or not isinstance(c.get('base_ref'), str):
        raise FactoryError('Invalid config version/base_ref')
    if not isinstance(c.get('timeout_seconds'), (int, float)) or c['timeout_seconds'] <= 0:
        raise FactoryError('timeout_seconds must be positive')
    if not isinstance(c.get('max_parallel'), int) or not 1 <= c['max_parallel'] <= 2:
        raise FactoryError('max_parallel must be 1 or 2')
    if (not isinstance(c.get('commands'), dict) or not all(isinstance(x, dict) for x in c['commands'].values())
            or not isinstance(c.get('checks'), list)):
        raise FactoryError('Config requires a commands object of command objects and a checks array')
    if c.get('workflow', 'classic') not in ('classic', 'egm'):
        raise FactoryError('workflow must be classic or egm')
    if 'skill_inventory' in c:
        validate_inventory(c['skill_inventory'])
    extra = c.get('protected_paths', [])
    if not isinstance(extra, list) or not all(isinstance(x, str) and x.strip() for x in extra):
        raise FactoryError('protected_paths must be a list of nonempty strings')
    policy = review_policy.validate(c.get('review_policy', {}))
    for role in review_policy.required_commands(policy):
        if role not in c['commands']:
            raise FactoryError('Missing required review command: ' + role)
    from repair import validate_policy as validate_repair_policy
    validate_repair_policy(c.get('repair_policy'))
    return c


COMPLEXITIES = ('routine', 'complex')


MAX_ATTEMPTS = 3


def attempt_limit(c):
    """All retry/repair/replacement paths share the project's total attempt budget."""
    return min(MAX_ATTEMPTS, (c.get('repair_policy') or {}).get('max_repairs', MAX_ATTEMPTS - 1) + 1)


def reserved(row):
    """Only active candidates and held pending/blocked tickets reserve paths."""
    return (row['state'] in ('READY', 'AWAITING_HUMAN', 'RUNNING', 'REVIEWING') or
            (row['state'] in ('PENDING', 'BLOCKED') and row.get('hold_reason') is not None))


def protected(p):
    parts = PurePosixPath(p).parts
    return any(x.lower() in {'.git', '.infra-factory', '.github', '.claude', '.codex', '.agents', 'agents.md', 'claude.md', 'skill.md'} for x in parts)


def within(p, root):
    p = PurePosixPath(p).as_posix()
    root = str(PurePosixPath(root)).rstrip('/')
    return p == root or p.startswith(root + '/')


def overlap(a, b):
    return any(within(x, y) or within(y, x) for x in a for y in b)


def changed_entries(repo, base, head):
    """Every path a commit touches, with rename detection off.

    Default rename detection reports only the destination, so a hook that deletes
    an out-of-scope file by renaming it onto an allowed path would otherwise
    look in-scope. Status letters and paths are NUL-separated pairs.
    """
    raw = git(repo, 'diff', '--name-status', '--no-renames', '-z', base, head)
    fields = raw.split('\0')
    entries = []
    for i in range(0, len(fields) - 1, 2):
        status, path = fields[i], fields[i + 1]
        if status and path:
            entries.append((status, path))
    return entries


def diff_paths(repo, base, head):
    """Paths a commit adds, modifies or deletes. Rename detection is off.

    `git diff --name-only` drops the source of a rename, so reviewers were asked
    to attest a file list that did not include the deleted path.
    """
    return sorted({path for _, path in changed_entries(repo, base, head)})


def assert_committed_scope(repo, ticket, base, head):
    for status, path in changed_entries(repo, base, head):
        if protected(path) or not any(within(path, x) for x in ticket['paths']):
            raise FactoryError(f'Committed change outside allowed paths ({status}): {path}')


def dirty(repo, allow_config=False):
    # Porcelain -z avoids ambiguity from spaces, quotes and newlines in filenames.
    raw = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain=v1', '-z', '--untracked-files=all'], timeout=60)
    fields = raw.decode(errors='surrogateescape').split('\0')
    paths = []
    i = 0
    while i < len(fields):
        item = fields[i]
        i += 1
        if not item:
            continue
        p = item[3:]
        if not (allow_config and p == '.infra-factory/config.json' and item[:2] == '??'):
            paths.append(p)
        if 'R' in item[:2] or 'C' in item[:2]:
            paths.append(fields[i])
            i += 1
    return paths


def scoped(worktree, ticket, base):
    if git(worktree, 'rev-parse', 'HEAD') != base:
        raise FactoryError('Worker/check changed HEAD; only controller may commit')
    paths = dirty(worktree)
    for p in paths:
        if protected(p) or not any(within(p, x) for x in ticket['paths']):
            raise FactoryError(f'Out-of-scope or protected change: {p}')
    return paths


def command(spec, substitutions):
    if not isinstance(spec, dict) or not isinstance(spec.get('argv'), list) or not spec['argv'] or any(not isinstance(x, str) or not x for x in spec['argv']):
        raise FactoryError('Commands require a nonempty argv array')
    args = []
    for arg in spec['argv']:
        for key, value in substitutions.items():
            arg = arg.replace('{' + key + '}', str(value))
        args.append(arg)
    return args


def kill_tree(p):
    if os.name == 'posix':
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        p.kill()  # Windows descendants need an external Job Object runner.


def interrupt(signum, frame):
    """SIGINT/SIGTERM: stop launching, kill owned process groups, unwind normally.

    Children run in their own sessions, so they never see a terminal Ctrl-C and
    previously outlived a terminated controller. Unwinding releases the lock and
    lets worker threads record BLOCKED instead of leaving stale RUNNING rows.
    """
    STOP.set()
    for p in list(ACTIVE):
        kill_tree(p)
    raise KeyboardInterrupt


def invoke(args, cwd, log, timeout, prompt=None, env=None, split_stderr=False):
    """Run one bounded command. split_stderr keeps machine-read stdout free of
    warnings/notices (stderr goes to <log>.stderr instead of being merged)."""
    with CLI_SLOTS, open(log, 'ab') as out, contextlib.ExitStack() as stack:
        if STOP.is_set():
            raise FactoryError('Interrupted before command start')
        err = stack.enter_context(open(str(log) + '.stderr', 'ab')) if split_stderr else subprocess.STDOUT
        p = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
                             stdout=out, stderr=err, env=env, start_new_session=(os.name == 'posix'))
        ACTIVE.add(p)
        try:
            if STOP.is_set():
                kill_tree(p)
            p.communicate(prompt.encode() if prompt is not None else None, timeout=timeout)
        except BaseException:
            kill_tree(p)
            p.wait()
            raise
        finally:
            ACTIVE.discard(p)
        if STOP.is_set():
            raise FactoryError('Interrupted by termination signal; its process group was killed')
        if p.returncode:
            raise FactoryError(f'Command exited {p.returncode}; see {log}')


def run_agent(spec, wt, prompt_path, result_path, log, timeout, prompt):
    prompt_path.write_text(prompt)
    args = command(spec, {'worktree': wt, 'prompt_file': prompt_path, 'result_file': result_path, 'model': spec.get('model', '')})
    invoke(args, wt, log, timeout, prompt if spec.get('stdin_prompt', False) else None)

