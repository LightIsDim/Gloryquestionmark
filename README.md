# FILECORE

Private filesystem-based file manager.

No database.

Filesystem is the single source of truth.

## Features

- Filesystem-only storage
- No PostgreSQL
- No MySQL
- No SQLite
- No MongoDB
- No Redis
- Recursive search
- Folder creation
- Folder rename
- Folder move
- Folder delete
- File upload
- Chunked large-file upload
- Resumable upload
- Streaming download
- HTTP Range support
- Preview
- Rename
- Move
- Delete
- Properties
- Disk usage monitoring
- File-based activity log
- HTTP Basic Authentication
- Docker support
- Mobile responsive UI

## Requirements

Python 3.11+

or

Docker / Docker Compose

## Local installation

Create virtual environment:

python3 -m venv .venv

Activate:

source .venv/bin/activate

Install dependencies:

pip install -r backend/requirements.txt

Create environment:

cp .env.example .env

Edit:

STORAGE_PATH=/absolute/path/to/storage

APP_USER=admin

APP_PASSWORD=your-long-password

Create storage:

mkdir -p storage

Run:

uvicorn backend.main:app --host 0.0.0.0 --port 8000

Open:

http://localhost:8000

## Docker

Create .env:

cp .env.example .env

Edit credentials.

Then:

docker compose up -d --build

Open:

http://localhost:8000

## Storage

All user data lives under:

/storage

Example:

/storage
├── Foto Vian
│   ├── foto1.jpg
│   └── Liburan
│       └── foto2.jpg
├── Dokumen
│   └── laporan.pdf
└── backup.zip

The application does not maintain file metadata in a database.

## Changing storage location

Change:

STORAGE_PATH=/storage

to:

STORAGE_PATH=/data/storage

No source-code changes are required.

With Docker:

volumes:
  - /data/storage:/storage

The application continues to use /storage inside the container.

## Large upload

Uploads use:

1. upload initialization
2. chunk upload
3. upload status
4. upload completion

Example:

5 GB file

    chunk 0
    chunk 1
    chunk 2
       ...
    chunk N

Chunks are temporarily stored under:

/storage/.uploads/

After completion they are assembled into the destination file.

The final file is written to a temporary file and atomically renamed into place.

## Resume upload

The frontend calls:

GET /api/upload/status?upload_id=...

Already uploaded chunks are skipped.

Therefore a disconnected upload can continue without retransmitting completed chunks.

## Download

Downloads are streamed.

The server does not call read() on the entire file.

HTTP Range requests are supported so clients can request:

bytes=0-1048575

or other ranges.

This is particularly useful for large video/audio files and resumable downloads.

## Search

Search walks the filesystem recursively.

There is no search database.

For example:

GET /api/search?q=liburan

can find:

/storage/Foto Vian/foto-liburan.jpg

and:

/storage/Video/video-liburan.mp4

## Activity log

Activity is stored at:

/storage/.system/activity.log

The log is not required to restore the filesystem.

Deleting the application database is therefore irrelevant because there is no database.

## Backup

Backup:

rsync -a /storage/ /backup/storage/

Restore:

rsync -a /backup/storage/ /storage/

The filesystem itself is the source of truth.

## Security

All user paths are treated as relative paths.

Requests such as:

../../etc/passwd

are rejected.

Absolute paths such as:

/etc/passwd

are rejected.

Symlinks that resolve outside the storage root are rejected.

Internal application directories:

.storage/.system
.storage/.uploads

are not exposed through the normal file browser.

For production:

- use a strong APP_PASSWORD
- use HTTPS
- put the application behind a reverse proxy
- restrict network access with firewall/VPN
- run the container as a dedicated non-root user where possible
- make regular backups

## Created timestamp

On systems that expose st_birthtime, FILECORE uses it.

On Linux filesystems where birth time is unavailable through Python's standard stat result, the implementation falls back to st_ctime.

Therefore "Created" should be interpreted as filesystem-provided creation/change metadata depending on the underlying OS/filesystem.

## API

GET /api/health

GET /api/files?path=

GET /api/properties?path=

POST /api/folder

PATCH /api/rename

POST /api/move

DELETE /api/delete

GET /api/search?q=

GET /api/storage

GET /api/activity

POST /api/upload/init

POST /api/upload/chunk

GET /api/upload/status

POST /api/upload/complete

GET /api/download?path=

GET /api/preview?path=

OpenAPI:

/api/docs