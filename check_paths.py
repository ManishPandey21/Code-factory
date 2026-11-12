"""Recognize literal in-repository paths named by trusted verification argv.

This does not interpret shell/code strings or follow wrapper imports. Those still
need explicit protected_paths or an externally controlled verification service.
"""
import os
import re
from pathlib import Path


def mutation_inputs(argv):
    """Protect the mutator executable/script, not its production destinations.

    Recognize Python's script position and plain script invocations for common
    interpreters. Inline code, modules, wrapper imports and unusual launcher
    flags still require explicit protected_paths, as with normal checks.
    """
    inputs = argv[:1]
    if not argv:
        return inputs
    launcher = Path(argv[0]).name.lower().removesuffix('.exe')
    if re.fullmatch(r'(?:python|pypy)(?:[0-9]+(?:\.[0-9]+)*)?', launcher):
        index = 1
        while index < len(argv):
            argument = argv[index]
            if argument in ('-c', '-m') or argument.startswith(('-c', '-m')):
                return inputs
            if argument in ('-W', '-X'):
                index += 2
                continue
            if argument == '--':
                return inputs + argv[index + 1:index + 2]
            if not argument.startswith('-'):
                return inputs + [argument]
            index += 1
    elif launcher in ('node', 'nodejs', 'ruby', 'perl', 'sh', 'bash', 'dash', 'zsh', 'pwsh', 'powershell'):
        if len(argv) > 1 and not argv[1].startswith('-'):
            inputs.append(argv[1])
    return inputs


def referenced_paths(config, repo, tracked_paths, source_repo=None):
    roots = {Path(repo).resolve(), Path(source_repo or repo).resolve()}
    known = set(tracked_paths)
    for name in tuple(known):
        known.update(p.as_posix() for p in Path(name).parents if p.as_posix() != '.')
    known.add('.')
    protected = set()
    commands = list(config.get('checks', []))
    commands += [check['argv'] for check in config.get('verification', {}).get('checks', [])]
    commands += [mutation_inputs(check['negative_control']['argv'])
                 for check in config.get('verification', {}).get('checks', [])
                 if 'negative_control' in check]
    for argv in commands:
        for arg in argv:
            # Flags with an attached value and pytest node selectors still name paths.
            value = arg.split('=', 1)[1] if arg.startswith('-') and '=' in arg else arg
            value = value.split('::', 1)[0]
            if not value or value.startswith('-') or '\x00' in value:
                continue
            for root in roots:
                expanded = value.replace('{worktree}', str(root))
                if '{' in expanded or '}' in expanded:
                    continue  # report locations and other transport placeholders
                # Normalize dot segments, but do not resolve a candidate symlink.
                candidate = Path(os.path.abspath(root / expanded))
                # Compare lexically first, then reconcile aliases ONLY up to
                # an ancestor identifying a trusted repository root. Preserve
                # every descendant component (including a deleted wrapper).
                anchors = [root]
                if not candidate.is_relative_to(root):
                    for ancestor in (candidate, *candidate.parents):
                        try:
                            if ancestor.resolve() == root:
                                anchors.append(ancestor)
                                break
                        except (OSError, RuntimeError):
                            continue
                for anchor in anchors:
                    if candidate.is_relative_to(anchor):
                        relative = candidate.relative_to(anchor).as_posix()
                        if relative in known:
                            protected.add(relative)
    return protected
