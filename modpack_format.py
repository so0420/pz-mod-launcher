"""Validate distribution metadata and ZIP paths before changing local files."""
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat


def folder_name(value):
    if (not isinstance(value, str) or value in ("", ".", "..")
            or any(c in value for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in value) or value.endswith((" ", "."))
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value)):
        raise ValueError("모드 폴더 또는 파일 이름이 올바르지 않습니다.")
    return value


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get("latest_version")) is not int or manifest["latest_version"] < 1:
        raise ValueError("manifest의 latest_version은 양의 정수여야 합니다.")
    versions = manifest.get("versions", [])
    if not isinstance(versions, list):
        raise ValueError("manifest의 versions 형식이 올바르지 않습니다.")
    seen = set()
    for entry in versions:
        if (not isinstance(entry, dict) or type(entry.get("version")) is not int
                or not 1 <= entry["version"] <= manifest["latest_version"] or entry["version"] in seen):
            raise ValueError("manifest 버전 기록이 올바르지 않습니다.")
        seen.add(entry["version"])
        for key in ("changed", "removed"):
            names = entry.get(key, [])
            if not isinstance(names, list):
                raise ValueError("manifest 모드 목록이 올바르지 않습니다.")
            for name in names:
                folder_name(name)
    digests = manifest.get("digests", {})
    if not isinstance(digests, dict):
        raise ValueError("manifest의 digests 형식이 올바르지 않습니다.")
    folded = set()
    for name in digests:
        folder_name(name)
        if name.casefold() in folded:
            raise ValueError("Windows에서 구분할 수 없는 모드 폴더 이름이 있습니다.")
        folded.add(name.casefold())
    archives = manifest.get("archives", {})
    if not isinstance(archives, dict) or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in archives.values()):
        raise ValueError("manifest의 압축파일 SHA-256 형식이 올바르지 않습니다.")
    archive_base = manifest.get("archive_base", "")
    if (not isinstance(archive_base, str) or archive_base.startswith("/") or "\\" in archive_base
            or (archive_base and any(p in ("", ".", "..") for p in archive_base.split("/")))):
        raise ValueError("manifest의 archive_base는 상대 경로여야 합니다.")
    for part in archive_base.split("/") if archive_base else []:
        folder_name(part)
    return manifest


def archive_members(archive):
    members, seen = [], set()
    for entry in archive.infolist():
        name = entry.filename
        path = PurePosixPath(name)
        if path.is_absolute() or "\\" in name or any(p in ("", ".", "..") for p in name.rstrip("/").split("/")):
            raise ValueError(f"안전하지 않은 ZIP 경로입니다: {name}")
        for part in path.parts:
            folder_name(part)
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ValueError("링크를 포함한 ZIP은 설치할 수 없습니다.")
        if name == "manifest.json" or name.startswith("runtime/"):
            continue  # Legacy runtime patches are not installed automatically.
        folded = name.rstrip("/").casefold()
        if folded in seen:
            raise ValueError(f"중복된 ZIP 경로입니다: {name}")
        seen.add(folded)
        if not entry.is_dir() and len(path.parts) < 2:
            raise ValueError("ZIP에는 모드별 최상위 폴더가 필요합니다.")
        members.append(entry)
    return members


def verify_archive(path, manifest, name):
    expected = manifest.get("archives", {}).get(name) if manifest else None
    if expected:
        with Path(path).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected:
            raise ValueError(f"압축파일 SHA-256 검증에 실패했습니다: {name}")
