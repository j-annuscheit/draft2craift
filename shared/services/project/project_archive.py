"""Archive helpers for project import/export in ``.d2c`` format."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import zipfile


D2C_EXTENSION = ".d2c"
REQUIRED_PROJECT_DIRS = ("canvas", "knowledge", "rag", "chat", "logs")


class ProjectArchiveError(ValueError):
    """Raised when a project archive is invalid or unsafe."""


def ensure_archive_extension(path: str | Path) -> Path:
    """Return *path* with a ``.d2c`` suffix."""
    raw_text = str(path or "").strip()
    if not raw_text:
        raise ProjectArchiveError("Archive path is empty.")
    raw = Path(raw_text)
    if raw.suffix.lower() == D2C_EXTENSION:
        return raw
    if raw.suffix:
        return raw.with_suffix(D2C_EXTENSION)
    return raw.with_name(f"{raw.name}{D2C_EXTENSION}")


def create_project_archive(source_folder: str | Path, archive_path: str | Path) -> Path:
    """Pack project folder contents into a ZIP archive with ``.d2c`` extension."""
    source = Path(str(source_folder or "")).expanduser().resolve(strict=False)
    if not source.exists() or not source.is_dir():
        raise ProjectArchiveError(f"Project folder does not exist: {source}")

    target = ensure_archive_extension(archive_path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(target, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in _iter_entries(source):
            arcname = entry.relative_to(source).as_posix()
            if entry.is_dir():
                archive.writestr(f"{arcname}/", b"")
                continue
            if entry.is_file():
                archive.write(entry, arcname=arcname)

    return target


def extract_project_archive(archive_path: str | Path, destination: str | Path) -> Path:
    """Extract a validated project archive to *destination* and return project root."""
    archive_file = Path(str(archive_path or "")).expanduser().resolve(strict=False)
    if not archive_file.exists() or not archive_file.is_file():
        raise ProjectArchiveError(f"Archive file does not exist: {archive_file}")

    destination_root = Path(str(destination or "")).expanduser().resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_file, mode="r") as archive:
            project_root_prefix = _validate_archive_members(archive)
            corrupted_member = archive.testzip()
            if corrupted_member is not None:
                raise ProjectArchiveError(
                    f"Archive contains corrupted entry: {corrupted_member}"
                )
            _safe_extract_all(archive, destination_root)
    except zipfile.BadZipFile as exc:
        raise ProjectArchiveError("File is not a valid ZIP archive.") from exc

    project_root = (
        destination_root
        if str(project_root_prefix) in {"", "."}
        else destination_root / Path(*project_root_prefix.parts)
    )
    manifest = project_root / "project.json"
    if not manifest.exists() or not manifest.is_file():
        raise ProjectArchiveError("Archive extraction did not produce project.json.")
    return project_root


def _iter_entries(source: Path) -> list[Path]:
    return sorted(
        [entry for entry in source.rglob("*")],
        key=lambda item: item.relative_to(source).as_posix(),
    )


def _validate_archive_members(archive: zipfile.ZipFile) -> PurePosixPath:
    infos = archive.infolist()
    if not infos:
        raise ProjectArchiveError("Archive is empty.")

    normalized_paths = [_normalize_member_name(info.filename) for info in infos]
    project_roots = {
        member.parent
        for member in normalized_paths
        if member.name == "project.json"
    }
    if not project_roots:
        raise ProjectArchiveError("Archive does not contain project.json.")
    if len(project_roots) > 1:
        raise ProjectArchiveError(
            "Archive contains multiple project roots. Expected exactly one project.json."
        )
    project_root = next(iter(project_roots))

    missing_dirs: list[str] = []
    for directory in REQUIRED_PROJECT_DIRS:
        if not _has_required_directory(normalized_paths, project_root, directory):
            missing_dirs.append(directory)
    if missing_dirs:
        raise ProjectArchiveError(
            "Archive is missing required folders: " + ", ".join(missing_dirs)
        )
    return project_root


def _has_required_directory(
    members: list[PurePosixPath],
    project_root: PurePosixPath,
    directory: str,
) -> bool:
    folder_path = project_root / directory
    folder_prefix = f"{folder_path.as_posix().rstrip('/')}/"
    for member in members:
        member_text = member.as_posix()
        if member == folder_path:
            return True
        if member_text.startswith(folder_prefix):
            return True
    return False


def _normalize_member_name(name: str) -> PurePosixPath:
    raw = str(name or "").replace("\\", "/").strip()
    if not raw:
        raise ProjectArchiveError("Archive contains an empty member path.")

    posix = PurePosixPath(raw)
    if posix.is_absolute():
        raise ProjectArchiveError(f"Archive contains unsafe absolute path: {name}")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ProjectArchiveError(f"Archive contains unsafe relative path: {name}")
    if posix.parts and posix.parts[0].endswith(":"):
        raise ProjectArchiveError(f"Archive contains unsafe drive path: {name}")
    return posix


def _safe_extract_all(archive: zipfile.ZipFile, destination: Path) -> None:
    destination_root = destination.resolve(strict=False)
    for info in archive.infolist():
        member = _normalize_member_name(info.filename)
        target_path = (destination_root / Path(*member.parts)).resolve(strict=False)
        if not _is_relative_to(target_path, destination_root):
            raise ProjectArchiveError(f"Archive path escapes extraction root: {member}")

        if info.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, mode="r") as source, open(target_path, "wb") as handle:
            shutil.copyfileobj(source, handle)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
