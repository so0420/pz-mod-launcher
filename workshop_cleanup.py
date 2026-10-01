"""Delete only PZ Workshop caches from explicitly discovered Steam libraries."""
import os
from pathlib import Path
import shutil
import stat

import game_runtime

APP_ID = "108600"
RELATIVE_ROOT = Path("steamapps") / "workshop" / "content" / APP_ID


def find_workshop_roots(libraries):
    roots = []
    seen = set()
    for library in libraries:
        library = Path(library)
        if not library.is_absolute():
            raise ValueError("Steam 라이브러리 경로는 절대 경로여야 합니다.")
        root = library.resolve() / RELATIVE_ROOT
        key = os.path.normcase(str(root))
        if key not in seen and root.is_dir():
            roots.append(root)
            seen.add(key)
    return roots


def _check_path(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        # 0x400 = FILE_ATTRIBUTE_REPARSE_POINT (includes Windows junctions).
        raise ValueError(f"연결된 폴더·파일은 워크샵 강제 삭제 대상에서 제외합니다: {path}")
    return info


def validate_workshop_roots(roots):
    validated = []
    seen = set()
    for value in roots:
        root = Path(value)
        if not root.is_absolute() or tuple(part.lower() for part in root.parts[-4:]) != (
                "steamapps", "workshop", "content", APP_ID):
            raise ValueError(f"좀보이드 워크샵 캐시 경로가 아닙니다: {root}")
        library = root.parents[3].resolve()
        expected = library / RELATIVE_ROOT
        if os.path.normcase(str(root)) != os.path.normcase(str(expected)):
            raise ValueError(f"워크샵 캐시 경로를 확인할 수 없습니다: {root}")
        missing = False
        for path in [root.parents[2], root.parents[1], root.parent, root]:
            try:
                info = _check_path(path)
            except FileNotFoundError:
                missing = True
                break
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"워크샵 캐시 경로가 폴더가 아닙니다: {path}")
        if missing:
            continue
        if root.resolve() != expected or not root.resolve().is_relative_to(library):
            raise ValueError(f"Steam 라이브러리 밖의 경로는 삭제하지 않습니다: {root}")
        # Refuse nested links as well; inspect every cache before deleting any.
        pending = [root]
        while pending:
            for path in pending.pop().iterdir():
                info = _check_path(path)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
        key = os.path.normcase(str(root))
        if key not in seen:
            validated.append(root)
            seen.add(key)
    return validated


def _retry_readonly(function, path, exc_info):
    error = exc_info[1]
    if not isinstance(error, PermissionError):
        raise error
    _check_path(Path(path))
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    function(path)


def remove_workshop(roots):
    game_runtime.ensure_game_stopped()
    roots = validate_workshop_roots(roots)
    removed = []
    for root in roots:
        # Revalidate the exact absolute target immediately before recursive removal.
        if not validate_workshop_roots([root]):
            continue
        shutil.rmtree(root, onerror=_retry_readonly)
        removed.append(root)
    return removed
