"""Construct fresh verification checkouts and scrub check-process environments.

These are reproducibility controls, NOT an OS security sandbox. A process running
as the controller's user can still access other files, processes and the network.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile


GIT_TIMEOUT_SECONDS = 120
_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ColdWorkspaceError(RuntimeError):
    """A fresh, pinned verification checkout could not be established."""


def _minimal_env():
    # In particular, omit GIT_*, token/API variables, SSH_AUTH_SOCK, PYTHONPATH,
    # npm config and inherited provider/session state. PATH is a trusted host
    # input; operators must not populate it from candidate-controlled locations.
    allowed = ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC",
               "ComSpec", "PATHEXT")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.setdefault("PATH", os.defpath)
    env.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    return env


def env_for_checks(checkout, namespace):
    """Return a fresh minimal environment with private HOME/temp/cache paths.

    Each call creates new directories under checkout.parent; retain them with
    attempt evidence and remove through the operator's normal cleanup process.
    Namespace is passed as data, never interpreted as a pathname or shell input.
    No authentication/configuration from the controller's home is inherited.
    """
    checkout = Path(checkout).resolve()
    if not isinstance(namespace, str) or not namespace or "\x00" in namespace:
        raise ColdWorkspaceError("namespace must be a nonempty string without NUL")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    prefix = ".factory-home-" + hashlib.sha256(namespace.encode()).hexdigest()[:12] + "-"
    home = Path(tempfile.mkdtemp(prefix=prefix, dir=checkout.parent))
    # mkdtemp provides 0700 on POSIX; chmod makes the intended mode explicit.
    home.chmod(0o700)
    env = _minimal_env()
    env.update({"HOME": str(home), "USERPROFILE": str(home),
                "FACTORY_NAMESPACE": namespace})
    for key, subdir in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                        ("XDG_DATA_HOME", "data"), ("TMPDIR", "tmp")):
        path = home / subdir
        path.mkdir(mode=0o700)
        env[key] = str(path)
    env["TEMP"] = env["TMP"] = env["TMPDIR"]
    return env


def _git(destination, env, *args):
    try:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=" + str(Path(env["HOME"]) / "empty-hooks"),
             "-c", "protocol.file.allow=always", "-c", "gc.auto=0",
             "-C", str(destination), *args],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ColdWorkspaceError("Fresh-checkout Git operation failed: " + str(exc)) from exc
    if result.returncode:
        raise ColdWorkspaceError("Fresh-checkout Git operation failed: " + result.stderr.strip())
    return result.stdout.strip()


def clone_candidate(source, destination, head, base):
    """Fetch exact objects into a new independent repo; return its checkout path.

    init+fetch deliberately replaces local clone optimizations: there are no
    hardlinks, alternates, copied source config/hooks or shared Git directory.
    Fetching explicit object IDs imports only their reachable history, not other
    branch names or the builder's worktree/ignored files/transcripts. No remote
    is installed. An existing destination is never reused or deleted.
    """
    if not all(isinstance(x, str) and _OBJECT_ID.fullmatch(x) for x in (head, base)):
        raise ColdWorkspaceError("head and base must be full lowercase Git object IDs")
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ColdWorkspaceError("Cold checkout destination must not already exist")
    destination.mkdir(parents=True)
    env = env_for_checks(destination, "git-bootstrap-" + head)
    # Disable global/system Git config, templates and interactive credentials.
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0"})
    _git(destination, env, "init", "--quiet", "--template=",
         "--object-format=" + ("sha256" if len(head) == 64 else "sha1"))
    _git(destination, env, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
         "--no-write-fetch-head", str(source), head, base)
    if _git(destination, env, "rev-parse", head + "^{commit}") != head:
        raise ColdWorkspaceError("Candidate object is not the exact requested commit")
    if _git(destination, env, "rev-parse", base + "^{commit}") != base:
        raise ColdWorkspaceError("Base object is not the exact requested commit")
    _git(destination, env, "merge-base", "--is-ancestor", base, head)
    _git(destination, env, "checkout", "--quiet", "--detach", head)
    if _git(destination, env, "rev-parse", "HEAD") != head:
        raise ColdWorkspaceError("Cold checkout HEAD does not match candidate")
    if _git(destination, env, "remote"):
        raise ColdWorkspaceError("Cold checkout unexpectedly has a remote")
    return destination
