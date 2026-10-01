"""Build mods.zip, per-mod ZIPs, and an incremental-update manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from modpack_format import folder_name, validate_manifest


def _files(root):
    paths = sorted(root.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("모드 원본에 링크가 있습니다.")
    return [p for p in paths if p.is_file()]


def folder_digest(root):
    digest = hashlib.sha256()
    for path in _files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def add_tree(archive, root):
    for path in _files(root):
        archive.write(path, root.name + "/" + path.relative_to(root).as_posix())


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(mods_dir, out, version, note=""):
    mods_dir, out = Path(mods_dir).resolve(), Path(out).resolve()
    if version < 1:
        raise ValueError("버전 번호는 양의 정수여야 합니다.")
    if out == mods_dir or out.is_relative_to(mods_dir):
        raise ValueError("출력 폴더는 모드 원본 폴더 밖에 지정해주세요.")
    if not mods_dir.is_dir() or mods_dir.is_symlink():
        raise ValueError("모드 원본 폴더를 확인해주세요.")
    sources = sorted(p for p in mods_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    if not sources:
        raise ValueError("모드 폴더가 없습니다.")
    folded = set()
    for source in sources:
        folder_name(source.name)
        if source.is_symlink() or source.name.casefold() in folded:
            raise ValueError("링크 또는 중복 모드 폴더가 있습니다.")
        folded.add(source.name.casefold())
        if not any(p.name == "mod.info" for p in _files(source)):
            raise ValueError(f"mod.info가 없는 폴더입니다: {source.name}")
    manifest_path = out / "manifest.json"
    previous = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8"))) if manifest_path.exists() else {}
    if version <= previous.get("latest_version", 0):
        raise ValueError("버전은 직전 배포보다 커야 합니다.")
    digests = {p.name: folder_digest(p) for p in sources}
    old = previous.get("digests", {})
    changed = [name for name in digests if old.get(name) != digests[name]]
    removed = sorted(set(old) - set(digests))
    manifest = {"latest_version": version, "versions": previous.get("versions", []) + [
        {"version": version, "changed": changed, "removed": removed, "note": note}],
        "digests": digests, "archives": {}}
    (out / "mods").mkdir(parents=True, exist_ok=True)
    for source in sources:
        path = out / "mods" / (source.name + ".zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            add_tree(archive, source)
        manifest["archives"]["mods/" + path.name] = sha256(path)
    for name in removed:
        (out / "mods" / (name + ".zip")).unlink(missing_ok=True)
    full = out / "mods.zip"
    with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            add_tree(archive, source)
    manifest["archives"]["mods.zip"] = sha256(full)
    validate_manifest(manifest)
    # Publish metadata last so clients cannot see a version before its ZIPs exist.
    temporary = out / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mods-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("dist/modpack"))
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    manifest = build(args.mods_dir, args.out, args.version, args.note)
    print(f"Built v{manifest['latest_version']}: changed={len(manifest['versions'][-1]['changed'])}, removed={len(manifest['versions'][-1]['removed'])}")
    print("Distribution:", args.out.resolve())


if __name__ == "__main__":
    main()
