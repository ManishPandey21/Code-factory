"""Check links below a trusted root without resolving away an unsafe descendant.

Repository roots are explicitly chosen by the controller. The OS temporary root
is also trusted (macOS commonly reaches it through /var or /tmp aliases). Nothing
below those anchors is implicitly trusted. These checks are not race-proof OS
isolation against another process running as the same user.
"""
import os
from pathlib import Path
import stat
import tempfile


def checked_path(path, *, root=None):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Path must not contain parent traversal')
    if root is None:
        roots = [Path(tempfile.gettempdir()).absolute()]
        if os.name == 'posix':
            roots += [Path('/tmp'), Path('/var/tmp')]
        temporary = next((p for p in roots if path.is_relative_to(p)), None)
        # Only the selected OS temp root may have system aliases. A nested link
        # remains a descendant to check, even if its target stays inside temp.
        root = temporary if temporary is not None else Path(path.anchor)
    root = Path(root).absolute()
    if '..' in root.parts or not path.is_relative_to(root):
        raise ValueError('Path must be within its trusted root')
    relative = path.relative_to(root)
    current = root.resolve(strict=True)
    for component in relative.parts:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue  # outputs may not exist yet; existing ancestors still checked
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Path must not contain symlinks or reparse points: ' + str(current))
    return current
