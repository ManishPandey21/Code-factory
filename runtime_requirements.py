"""Fail early when the local Git cannot provide the cold-checkout contract."""
import re
import subprocess

MIN_GIT = (2, 29)


def require_git_version():
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True,
                                encoding='utf-8', timeout=10)
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise ValueError('Git >= 2.29 is required; cannot determine installed version') from exc
    match = re.match(r'^git version (\d+)\.(\d+)(?=[.\s-]|$)', result.stdout.strip())
    if result.returncode or not match:
        raise ValueError('Git >= 2.29 is required; unrecognized git --version output')
    version = tuple(map(int, match.groups()))
    if version < MIN_GIT:
        raise ValueError('Git >= 2.29 is required for independent cold checkouts; found ' + result.stdout.strip())
    return version
