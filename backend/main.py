from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


load_dotenv()


# ============================================================
# CONFIG
# ============================================================

STORAGE_PATH = Path(
    os.getenv("STORAGE_PATH", "./storage")
).expanduser().resolve()

MAX_FILE_SIZE = os.getenv("MAX_FILE_SIZE", "10GB")

CHUNK_SIZE = int(
    os.getenv("UPLOAD_CHUNK_SIZE", str(16 * 1024 * 1024))
)

APP_USER = os.getenv("APP_USER", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# Internal application directories.
SYSTEM_DIR_NAME = ".system"
UPLOADS_DIR_NAME = ".uploads"

SYSTEM_DIR = STORAGE_PATH / SYSTEM_DIR_NAME
UPLOADS_DIR = STORAGE_PATH / UPLOADS_DIR_NAME
ACTIVITY_LOG = SYSTEM_DIR / "activity.log"

MAX_BYTES = 10 * 1024 * 1024 * 1024


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="FILECORE",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

security = HTTPBasic(auto_error=False)

operation_lock = threading.RLock()


# ============================================================
# MODELS
# ============================================================

class PathRequest(BaseModel):
    path: str = ""


class RenameRequest(BaseModel):
    path: str
    new_name: str


class MoveRequest(BaseModel):
    source: str
    destination: str


class DeleteRequest(BaseModel):
    path: str


class FolderRequest(BaseModel):
    parent: str = ""
    name: str


class UploadInitRequest(BaseModel):
    filename: str
    path: str = ""
    size: int


class UploadCompleteRequest(BaseModel):
    upload_id: str


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup() -> None:
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    ACTIVITY_LOG.touch(exist_ok=True)

    # Do not allow a symlink to redirect storage.
    if STORAGE_PATH.is_symlink():
        raise RuntimeError("STORAGE_PATH must not be a symbolic link")


# ============================================================
# AUTH
# ============================================================

def require_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
):
    """
    HTTP Basic Auth.

    Authentication is intentionally disabled if APP_USER /
    APP_PASSWORD are empty, which is convenient for local development.

    Production deployment should ALWAYS configure both.
    """

    if not APP_USER or not APP_PASSWORD:
        return True

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    valid_user = secrets.compare_digest(
        credentials.username,
        APP_USER,
    )

    valid_password = secrets.compare_digest(
        credentials.password,
        APP_PASSWORD,
    )

    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return True


# ============================================================
# SECURITY / PATH MANAGEMENT
# ============================================================

def reject_special_internal_path(relative: Path) -> None:
    """
    Prevent users from interacting with internal application
    directories through the normal file manager.
    """

    parts = relative.parts

    if SYSTEM_DIR_NAME in parts or UPLOADS_DIR_NAME in parts:
        raise HTTPException(
            status_code=403,
            detail="Internal application path is not accessible",
        )


def safe_path(
    user_path: str,
    *,
    allow_root: bool = True,
    must_exist: bool = False,
) -> Path:
    """
    Convert a client-supplied relative path into a safe absolute path.

    Security properties:
    - Client cannot supply arbitrary absolute filesystem paths.
    - '..' traversal is rejected.
    - Symlinks cannot escape STORAGE_PATH.
    - Internal application directories are hidden.
    """

    if user_path is None:
        user_path = ""

    user_path = user_path.strip()

    # Normalize browser-style paths.
    user_path = user_path.replace("\\", "/")

    if user_path.startswith("/"):
        # API paths are relative to /storage.
        user_path = user_path.lstrip("/")

    relative = Path(user_path)

    if relative.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="Absolute paths are not allowed",
        )

    if ".." in relative.parts:
        raise HTTPException(
            status_code=400,
            detail="Path traversal is not allowed",
        )

    reject_special_internal_path(relative)

    candidate = (STORAGE_PATH / relative).resolve(strict=False)

    try:
        candidate.relative_to(STORAGE_PATH)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Path escapes storage root",
        )

    if not allow_root and candidate == STORAGE_PATH:
        raise HTTPException(
            status_code=400,
            detail="Operation on storage root is not allowed",
        )

    if must_exist and not candidate.exists():
        raise HTTPException(
            status_code=404,
            detail="Path not found",
        )

    # If the target exists, resolve() above ensures symlinks remain
    # under STORAGE_PATH.
    if candidate.exists():
        try:
            candidate.resolve().relative_to(STORAGE_PATH)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail="Symlink escapes storage root",
            )

    return candidate


def relative_path(path: Path) -> str:
    """
    Convert absolute filesystem path to frontend-relative path.
    """

    try:
        rel = path.resolve().relative_to(STORAGE_PATH)
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail="Internal path error",
        )

    if str(rel) == ".":
        return ""

    return rel.as_posix()


def clean_name(name: str) -> str:
    """
    Validate a single filename/folder name.

    A name must never contain path separators.
    """

    name = name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Name cannot be empty",
        )

    if name in {".", ".."}:
        raise HTTPException(
            status_code=400,
            detail="Invalid name",
        )

    if "/" in name or "\\" in name:
        raise HTTPException(
            status_code=400,
            detail="Name must not contain path separators",
        )

    if "\x00" in name:
        raise HTTPException(
            status_code=400,
            detail="Invalid null character",
        )

    return name


# ============================================================
# FILESYSTEM HELPERS
# ============================================================

def file_type(path: Path) -> str:
    if path.is_dir():
        return "Folder"

    mime, _ = mimetypes.guess_type(path.name)

    if mime:
        return mime

    return "Unknown"


def iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(
        timestamp,
        timezone.utc,
    ).astimezone().isoformat()


def file_metadata(path: Path) -> dict:
    st = path.stat()

    # st_birthtime exists on some platforms.
    # On Linux it falls back to ctime.
    created = getattr(st, "st_birthtime", st.st_ctime)

    return {
        "name": path.name,
        "path": relative_path(path),
        "type": file_type(path),
        "is_dir": path.is_dir(),
        "size": st.st_size if path.is_file() else 0,
        "created": iso_time(created),
        "modified": iso_time(st.st_mtime),
    }


def directory_stats(path: Path) -> tuple[int, int, int]:
    files = 0
    folders = 0
    total_size = 0

    for root, dirs, filenames in os.walk(
        path,
        followlinks=False,
    ):
        # Hide internal dirs.
        dirs[:] = [
            d
            for d in dirs
            if d not in {
                SYSTEM_DIR_NAME,
                UPLOADS_DIR_NAME,
            }
        ]

        folders += len(dirs)

        for filename in filenames:
            try:
                p = Path(root) / filename

                if p.is_symlink():
                    continue

                st = p.stat()

                if stat.S_ISREG(st.st_mode):
                    files += 1
                    total_size += st.st_size

            except OSError:
                continue

    return files, folders, total_size


def log_activity(action: str, path: str = "") -> None:
    """
    Activity log contains only operational information.
    No password or authentication data is written.
    """

    timestamp = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    line = {
        "time": timestamp,
        "action": action,
        "path": path,
    }

    with operation_lock:
        with ACTIVITY_LOG.open(
            "a",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(
                line,
                ensure_ascii=False,
            ) + "\n")


def recent_activity(limit: int = 30) -> list[dict]:
    if not ACTIVITY_LOG.exists():
        return []

    try:
        lines = ACTIVITY_LOG.read_text(
            encoding="utf-8",
        ).splitlines()

        result = []

        for line in lines[-limit:]:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return list(reversed(result))

    except OSError:
        return []


def iter_file_range(
    path: Path,
    start: int,
    end: int,
) -> Iterator[bytes]:
    """
    Stream a byte range without loading the entire file into RAM.
    """

    remaining = end - start + 1

    with path.open("rb") as f:
        f.seek(start)

        while remaining > 0:
            chunk = f.read(
                min(CHUNK_SIZE, remaining)
            )

            if not chunk:
                break

            remaining -= len(chunk)

            yield chunk


# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/api/health",
    dependencies=[Depends(require_auth)],
)
def health():
    usage = shutil.disk_usage(STORAGE_PATH)

    return {
        "status": "online",
        "storage_path": str(STORAGE_PATH),
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
    }


# ============================================================
# FILE LISTING
# ============================================================

@app.get(
    "/api/files",
    dependencies=[Depends(require_auth)],
)
def list_files(path: str = Query("")):
    directory = safe_path(
        path,
        must_exist=True,
    )

    if not directory.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Path is not a directory",
        )

    items = []

    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    for entry in entries:
        if entry.name in {
            SYSTEM_DIR_NAME,
            UPLOADS_DIR_NAME,
        }:
            continue

        try:
            # Do not expose symlinks.
            if entry.is_symlink():
                continue

            items.append(file_metadata(entry))

        except OSError:
            continue

    items.sort(
        key=lambda item: (
            not item["is_dir"],
            item["name"].lower(),
        )
    )

    return {
        "path": relative_path(directory),
        "items": items,
    }


# ============================================================
# PROPERTIES
# ============================================================

@app.get(
    "/api/properties",
    dependencies=[Depends(require_auth)],
)
def properties(path: str):
    target = safe_path(
        path,
        must_exist=True,
    )

    metadata = file_metadata(target)

    if target.is_dir():
        files, folders, total_size = directory_stats(target)

        metadata.update({
            "files": files,
            "folders": folders,
            "total_size": total_size,
        })

    return metadata


# ============================================================
# CREATE FOLDER
# ============================================================

@app.post(
    "/api/folder",
    dependencies=[Depends(require_auth)],
)
def create_folder(request: FolderRequest):
    parent = safe_path(
        request.parent,
        must_exist=True,
    )

    if not parent.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Parent is not a directory",
        )

    name = clean_name(request.name)

    destination = safe_path(
        f"{request.parent.strip('/')}/{name}".strip("/"),
    )

    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="Folder already exists",
        )

    with operation_lock:
        destination.mkdir(
            parents=False,
            exist_ok=False,
        )

    log_activity(
        "CREATE_FOLDER",
        relative_path(destination),
    )

    return {
        "success": True,
        "path": relative_path(destination),
    }


# ============================================================
# RENAME
# ============================================================

@app.patch(
    "/api/rename",
    dependencies=[Depends(require_auth)],
)
def rename(request: RenameRequest):
    source = safe_path(
        request.path,
        allow_root=False,
        must_exist=True,
    )

    new_name = clean_name(request.new_name)

    destination = source.parent / new_name

    # Validate destination after joining.
    destination = safe_path(
        relative_path(destination),
        allow_root=False,
    )

    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="File or folder already exists",
        )

    with operation_lock:
        source.rename(destination)

    log_activity(
        "RENAME",
        f"{relative_path(source)} -> {relative_path(destination)}",
    )

    return {
        "success": True,
        "path": relative_path(destination),
    }


# ============================================================
# MOVE
# ============================================================

@app.post(
    "/api/move",
    dependencies=[Depends(require_auth)],
)
def move(request: MoveRequest):
    source = safe_path(
        request.source,
        allow_root=False,
        must_exist=True,
    )

    destination_dir = safe_path(
        request.destination,
        must_exist=True,
    )

    if not destination_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Destination is not a directory",
        )

    # Prevent moving a directory into itself.
    if source.is_dir():
        try:
            destination_dir.resolve().relative_to(
                source.resolve()
            )

            raise HTTPException(
                status_code=400,
                detail="Cannot move folder into itself",
            )

        except ValueError:
            pass

    destination = destination_dir / source.name

    destination = safe_path(
        relative_path(destination),
        allow_root=False,
    )

    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="Destination already exists",
        )

    with operation_lock:
        shutil.move(
            str(source),
            str(destination),
        )

    log_activity(
        "MOVE",
        f"{relative_path(source)} -> {relative_path(destination)}",
    )

    return {
        "success": True,
        "path": relative_path(destination),
    }


# ============================================================
# DELETE
# ============================================================

@app.delete(
    "/api/delete",
    dependencies=[Depends(require_auth)],
)
def delete(request: DeleteRequest):
    target = safe_path(
        request.path,
        allow_root=False,
        must_exist=True,
    )

    is_dir = target.is_dir()

    with operation_lock:
        if is_dir:
            shutil.rmtree(target)
        else:
            target.unlink()

    log_activity(
        "DELETE_FOLDER" if is_dir else "DELETE",
        request.path,
    )

    return {
        "success": True,
    }


# ============================================================
# SEARCH
# ============================================================

@app.get(
    "/api/search",
    dependencies=[Depends(require_auth)],
)
def search(
    q: str = Query(..., min_length=1),
):
    query = q.strip().lower()

    if not query:
        return {"results": []}

    results = []

    for root, dirs, filenames in os.walk(
        STORAGE_PATH,
        followlinks=False,
    ):
        dirs[:] = [
            d
            for d in dirs
            if d not in {
                SYSTEM_DIR_NAME,
                UPLOADS_DIR_NAME,
            }
        ]

        for name in dirs + filenames:
            if query not in name.lower():
                continue

            path = Path(root) / name

            try:
                if path.is_symlink():
                    continue

                results.append(file_metadata(path))

            except OSError:
                continue

            # Safety guard for huge trees.
            if len(results) >= 1000:
                return {
                    "results": results,
                    "truncated": True,
                }

    results.sort(
        key=lambda item: item["name"].lower()
    )

    return {
        "results": results,
        "truncated": False,
    }


# ============================================================
# STORAGE MONITOR
# ============================================================

@app.get(
    "/api/storage",
    dependencies=[Depends(require_auth)],
)
def storage():
    usage = shutil.disk_usage(STORAGE_PATH)

    percentage = (
        usage.used / usage.total * 100
        if usage.total
        else 0
    )

    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percentage": round(percentage, 2),
    }


# ============================================================
# ACTIVITY
# ============================================================

@app.get(
    "/api/activity",
    dependencies=[Depends(require_auth)],
)
def activity():
    return {
        "items": recent_activity()
    }


# ============================================================
# UPLOAD INIT
# ============================================================

@app.post(
    "/api/upload/init",
    dependencies=[Depends(require_auth)],
)
def upload_init(request: UploadInitRequest):
    filename = clean_name(request.filename)

    if request.size < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid file size",
        )

    if request.size > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds MAX_FILE_SIZE={MAX_FILE_SIZE}",
        )

    destination_dir = safe_path(
        request.path,
        must_exist=True,
    )

    if not destination_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Upload destination is not a directory",
        )

    upload_id = uuid.uuid4().hex

    upload_dir = UPLOADS_DIR / upload_id
    chunks_dir = upload_dir / "chunks"

    chunks_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    metadata = {
        "filename": filename,
        "path": relative_path(destination_dir),
        "size": request.size,
        "created": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    (upload_dir / "meta.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    return {
        "upload_id": upload_id,
        "chunk_size": CHUNK_SIZE,
        "total_chunks": (
            (request.size + CHUNK_SIZE - 1)
            // CHUNK_SIZE
            if request.size
            else 1
        ),
    }


# ============================================================
# UPLOAD CHUNK
# ============================================================

@app.post(
    "/api/upload/chunk",
    dependencies=[Depends(require_auth)],
)
def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    file: UploadFile = File(...),
):
    if not re.fullmatch(
        r"[a-f0-9]{32}",
        upload_id,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid upload ID",
        )

    if chunk_index < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid chunk index",
        )

    upload_dir = UPLOADS_DIR / upload_id
    chunks_dir = upload_dir / "chunks"

    if not upload_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail="Upload session not found",
        )

    destination = chunks_dir / f"{chunk_index:012d}.part"

    total_written = 0

    try:
        with destination.open("wb") as output:
            while True:
                chunk = file.file.read(CHUNK_SIZE)

                if not chunk:
                    break

                total_written += len(chunk)

                # Chunk-size safety guard.
                if total_written > CHUNK_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Chunk exceeds configured chunk size",
                    )

                output.write(chunk)

    finally:
        file.file.close()

    return {
        "success": True,
        "chunk_index": chunk_index,
        "bytes": total_written,
    }


# ============================================================
# UPLOAD STATUS
# ============================================================

@app.get(
    "/api/upload/status",
    dependencies=[Depends(require_auth)],
)
def upload_status(upload_id: str):
    if not re.fullmatch(
        r"[a-f0-9]{32}",
        upload_id,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid upload ID",
        )

    upload_dir = UPLOADS_DIR / upload_id
    meta_file = upload_dir / "meta.json"

    if not meta_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Upload session not found",
        )

    metadata = json.loads(
        meta_file.read_text(
            encoding="utf-8"
        )
    )

    received = []

    chunks_dir = upload_dir / "chunks"

    for part in chunks_dir.glob("*.part"):
        try:
            received.append(
                int(part.stem)
            )
        except ValueError:
            continue

    received.sort()

    return {
        "upload_id": upload_id,
        "filename": metadata["filename"],
        "path": metadata["path"],
        "size": metadata["size"],
        "received_chunks": received,
        "chunk_size": CHUNK_SIZE,
    }


# ============================================================
# UPLOAD COMPLETE
# ============================================================

@app.post(
    "/api/upload/complete",
    dependencies=[Depends(require_auth)],
)
def upload_complete(request: UploadCompleteRequest):
    upload_id = request.upload_id

    if not re.fullmatch(
        r"[a-f0-9]{32}",
        upload_id,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid upload ID",
        )

    upload_dir = UPLOADS_DIR / upload_id
    meta_file = upload_dir / "meta.json"
    chunks_dir = upload_dir / "chunks"

    if not meta_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Upload session not found",
        )

    metadata = json.loads(
        meta_file.read_text(
            encoding="utf-8"
        )
    )

    filename = clean_name(
        metadata["filename"]
    )

    destination_dir = safe_path(
        metadata["path"],
        must_exist=True,
    )

    destination = destination_dir / filename

    destination = safe_path(
        relative_path(destination),
        allow_root=False,
    )

    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="File already exists",
        )

    expected_size = int(metadata["size"])

    parts = []

    for part in chunks_dir.glob("*.part"):
        try:
            index = int(part.stem)
        except ValueError:
            continue

        parts.append((index, part))

    parts.sort(key=lambda x: x[0])

    if expected_size == 0:
        expected_chunks = 1
    else:
        expected_chunks = (
            expected_size + CHUNK_SIZE - 1
        ) // CHUNK_SIZE

    received_indexes = {
        index for index, _ in parts
    }

    expected_indexes = set(
        range(expected_chunks)
    )

    if received_indexes != expected_indexes:
        missing = sorted(
            expected_indexes - received_indexes
        )

        raise HTTPException(
            status_code=409,
            detail={
                "message": "Upload is incomplete",
                "missing_chunks": missing,
            },
        )

    # Write to a temporary file in the target directory.
    # os.replace() then makes finalization atomic on the same filesystem.
    temp_name = (
        f".{filename}."
        f"{uuid.uuid4().hex}.uploading"
    )

    temp_path = destination_dir / temp_name

    written = 0

    try:
        with temp_path.open("wb") as output:
            for _, part in parts:
                with part.open("rb") as input_file:
                    while True:
                        chunk = input_file.read(
                            CHUNK_SIZE
                        )

                        if not chunk:
                            break

                        written += len(chunk)

                        if written > expected_size:
                            raise HTTPException(
                                status_code=400,
                                detail="Uploaded data exceeds expected size",
                            )

                        output.write(chunk)

            output.flush()
            os.fsync(output.fileno())

        if written != expected_size:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Size mismatch: "
                    f"expected {expected_size}, "
                    f"received {written}"
                ),
            )

        with operation_lock:
            os.replace(
                temp_path,
                destination,
            )

        shutil.rmtree(
            upload_dir,
            ignore_errors=True,
        )

        log_activity(
            "UPLOAD",
            relative_path(destination),
        )

        return {
            "success": True,
            "path": relative_path(destination),
            "size": written,
        }

    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

        raise


# ============================================================
# DOWNLOAD / RANGE STREAM
# ============================================================

def parse_range(
    range_header: str | None,
    file_size: int,
) -> tuple[int, int]:
    if not range_header:
        return 0, file_size - 1

    if not range_header.startswith("bytes="):
        raise HTTPException(
            status_code=416,
            detail="Invalid Range header",
        )

    value = range_header[6:].split(",")[0].strip()

    if "-" not in value:
        raise HTTPException(
            status_code=416,
            detail="Invalid Range header",
        )

    start_str, end_str = value.split("-", 1)

    try:
        if start_str == "":
            # suffix range: bytes=-500
            suffix = int(end_str)

            if suffix <= 0:
                raise ValueError

            start = max(
                file_size - suffix,
                0,
            )

            end = file_size - 1

        else:
            start = int(start_str)

            if end_str:
                end = int(end_str)
            else:
                end = file_size - 1

    except ValueError:
        raise HTTPException(
            status_code=416,
            detail="Invalid Range header",
            headers={
                "Content-Range": f"bytes */{file_size}"
            },
        )

    if (
        start < 0
        or start >= file_size
        or end < start
    ):
        raise HTTPException(
            status_code=416,
            detail="Requested range not satisfiable",
            headers={
                "Content-Range": f"bytes */{file_size}"
            },
        )

    end = min(
        end,
        file_size - 1,
    )

    return start, end


@app.get(
    "/api/download",
    dependencies=[Depends(require_auth)],
)
def download(
    path: str,
    range_header: str | None = None,
):
    target = safe_path(
        path,
        must_exist=True,
    )

    if not target.is_file():
        raise HTTPException(
            status_code=400,
            detail="Not a file",
        )

    file_size = target.stat().st_size

    start, end = parse_range(
        range_header,
        file_size,
    )

    length = end - start + 1

    media_type = (
        mimetypes.guess_type(
            target.name
        )[0]
        or "application/octet-stream"
    )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Range": (
            f"bytes {start}-{end}/{file_size}"
        ),
        "Content-Disposition": (
            f'attachment; filename="{target.name}"'
        ),
        "X-Content-Type-Options": "nosniff",
    }

    log_activity(
        "DOWNLOAD",
        relative_path(target),
    )

    status_code = (
        206
        if range_header
        else 200
    )

    return StreamingResponse(
        iter_file_range(
            target,
            start,
            end,
        ),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


# ============================================================
# PREVIEW
# ============================================================

PREVIEW_TYPES = {
    "image/",
    "video/",
    "audio/",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/json",
}


def can_preview(mime: str) -> bool:
    return (
        any(
            mime.startswith(prefix)
            for prefix in [
                "image/",
                "video/",
                "audio/",
            ]
        )
        or mime in PREVIEW_TYPES
    )


@app.get(
    "/api/preview",
    dependencies=[Depends(require_auth)],
)
def preview(
    path: str,
    range_header: str | None = None,
):
    target = safe_path(
        path,
        must_exist=True,
    )

    if not target.is_file():
        raise HTTPException(
            status_code=400,
            detail="Not a file",
        )

    mime = (
        mimetypes.guess_type(
            target.name
        )[0]
        or "application/octet-stream"
    )

    if not can_preview(mime):
        raise HTTPException(
            status_code=415,
            detail="Preview not supported for this file type",
        )

    file_size = target.stat().st_size

    start, end = parse_range(
        range_header,
        file_size,
    )

    length = end - start + 1

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Range": (
            f"bytes {start}-{end}/{file_size}"
        ),
        "Content-Disposition": (
            f'inline; filename="{target.name}"'
        ),
        "X-Content-Type-Options": "nosniff",
    }

    status_code = (
        206
        if range_header
        else 200
    )

    return StreamingResponse(
        iter_file_range(
            target,
            start,
            end,
        ),
        status_code=status_code,
        media_type=mime,
        headers=headers,
    )


# ============================================================
# STATIC FRONTEND
# ============================================================

FRONTEND_DIR = (
    Path(__file__).resolve().parent.parent / "frontend"
)

app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIR,
        html=True,
    ),
    name="frontend",
)

# WHASRGKS[PODFHGBIB
@app.get(
    "/api/recent",
    dependencies=[Depends(require_auth)],
)
def recent_files(
    limit: int = Query(
        30,
        ge=1,
        le=100,
    ),
):
    """
    Return recently modified filesystem entries.

    No database/index is used.
    """

    results = []

    for root, dirs, filenames in os.walk(
        STORAGE_PATH,
        followlinks=False,
    ):
        dirs[:] = [
            d
            for d in dirs
            if d not in {
                SYSTEM_DIR_NAME,
                UPLOADS_DIR_NAME,
            }
        ]

        entries = (
            [Path(root) / d for d in dirs]
            +
            [Path(root) / f for f in filenames]
        )

        for entry in entries:

            try:
                if entry.is_symlink():
                    continue

                results.append(
                    file_metadata(entry)
                )

            except OSError:
                continue

    results.sort(
        key=lambda item: item["modified"],
        reverse=True,
    )

    return {
        "items": results[:limit],
    }
