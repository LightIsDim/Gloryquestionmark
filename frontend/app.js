const state = {
    currentPath: "",
    items: [],
    selected: null,
    view: "list",
    searchMode: false,
    uploadJobs: new Map(),
};

const $ = (selector) =>
    document.querySelector(selector);

const fileList = $("#file-list");
const breadcrumb = $("#breadcrumb");
const contextMenu = $("#context-menu");
const modalBackdrop = $("#modal-backdrop");
const modal = $("#modal");


// ============================================================
// UTILITIES
// ============================================================

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) return "--";

    if (bytes === 0) return "0 B";

    const units = [
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
        "PB",
    ];

    const i = Math.floor(
        Math.log(bytes) / Math.log(1024)
    );

    const value =
        bytes / Math.pow(1024, i);

    return `${value.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

function formatDate(date) {
    if (!date) return "--";

    return new Date(date).toLocaleString();
}

function showToast(message, error = false) {
    const container = $("#toast-container");

    const element = document.createElement("div");

    element.className =
        `toast${error ? " error" : ""}`;

    element.textContent = message;

    container.appendChild(element);

    setTimeout(() => {
        element.remove();
    }, 3500);
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
    });

    let payload = null;

    try {
        payload = await response.json();
    } catch {
        payload = null;
    }

    if (!response.ok) {
        const message =
            payload?.detail?.message ||
            payload?.detail ||
            `HTTP ${response.status}`;

        throw new Error(
            typeof message === "string"
                ? message
                : JSON.stringify(message)
        );
    }

    return payload;
}


// ============================================================
// PATH
// ============================================================

function pathJoin(a, b) {
    return [a, b]
        .filter(Boolean)
        .join("/")
        .replaceAll("//", "/");
}

function pathParent(path) {
    if (!path) return "";

    const parts = path.split("/");

    parts.pop();

    return parts.join("/");
}

function renderBreadcrumb() {
    const parts = state.currentPath
        ? state.currentPath.split("/")
        : [];

    let html = `
        <span
            class="crumb"
            data-path=""
            style="cursor:pointer"
        >
            / STORAGE
        </span>
    `;

    let current = "";

    for (const part of parts) {
        current = pathJoin(
            current,
            part
        );

        html += `
            <span> / </span>
            <span
                class="crumb"
                data-path="${escapeHtml(current)}"
                style="cursor:pointer"
            >
                ${escapeHtml(part)}
            </span>
        `;
    }

    breadcrumb.innerHTML = html;

    breadcrumb
        .querySelectorAll(".crumb")
        .forEach((element) => {
            element.addEventListener(
                "click",
                () => {
                    loadDirectory(
                        element.dataset.path
                    );
                }
            );
        });
}


// ============================================================
// FILE ICON
// ============================================================

function iconFor(item) {
    if (item.is_dir) return "📁";

    const name =
        item.name.toLowerCase();

    if (
        /\.(jpg|jpeg|png|gif|webp|svg|bmp|avif)$/
            .test(name)
    ) {
        return "🖼️";
    }

    if (
        /\.(mp4|mkv|avi|mov|webm|m4v)$/
            .test(name)
    ) {
        return "🎬";
    }

    if (
        /\.(mp3|wav|flac|ogg|m4a)$/
            .test(name)
    ) {
        return "♫";
    }

    if (
        /\.(zip|rar|7z|tar|gz|bz2|xz)$/
            .test(name)
    ) {
        return "▣";
    }

    if (
        /\.(pdf)$/
            .test(name)
    ) {
        return "PDF";
    }

    if (
        /\.(doc|docx|txt|md|rtf|odt)$/
            .test(name)
    ) {
        return "📄";
    }

    if (
        /\.(xls|xlsx|csv)$/
            .test(name)
    ) {
        return "▤";
    }

    return "FILE";
}


// ============================================================
// LOAD DIRECTORY
// ============================================================

async function loadDirectory(path = "") {
    try {
        state.searchMode = false;
        state.currentPath = path;

        const data = await api(
            `/api/files?path=${encodeURIComponent(path)}`
        );

        state.items = data.items;

        renderBreadcrumb();
        renderFiles();

        $("#search-input").value = "";

    } catch (error) {
        showToast(
            error.message,
            true
        );
    }
}


// ============================================================
// RENDER FILES
// ============================================================

function renderFiles() {
    fileList.className =
        state.view === "grid"
            ? "file-list grid"
            : "file-list";

    if (!state.items.length) {
        fileList.innerHTML = `
            <div class="empty">
                <div>
                    <strong>DIRECTORY EMPTY</strong>
                    No files or folders in this location.
                </div>
            </div>
        `;

        return;
    }

    fileList.innerHTML =
        state.items.map((item) => {

            const path = item.path;

            return `
                <div
                    class="file-row"
                    data-path="${escapeHtml(path)}"
                    data-dir="${item.is_dir ? "1" : "0"}"
                    ondblclick="openItem('${escapeHtml(path)}', ${item.is_dir})"
                >

                    <div class="file-icon">
                        ${iconFor(item)}
                    </div>

                    <div class="file-main">

                        <div class="file-name">
                            ${escapeHtml(item.name)}
                        </div>

                        <div class="file-path">
                            /${escapeHtml(item.path)}
                        </div>

                    </div>

                    <div class="file-type">
                        ${escapeHtml(item.type)}
                    </div>

                    <div class="file-date">
                        ${formatDate(item.modified)}
                    </div>

                    <button
                        class="context-button"
                        onclick="openContextMenu(event, '${escapeHtml(path)}')"
                    >
                        ⋮
                    </button>

                    <div class="file-size">
                        ${item.is_dir
                            ? "DIRECTORY"
                            : formatBytes(item.size)}
                    </div>

                </div>
            `;
        }).join("");
}


// ============================================================
// OPEN
// ============================================================

async function openItem(path, isDir) {
    if (isDir) {
        await loadDirectory(path);
        return;
    }

    const item = state.items.find(
        x => x.path === path
    );

    if (!item) return;

    const mime = item.type || "";

    if (
        mime.startsWith("image/") ||
        mime.startsWith("video/") ||
        mime.startsWith("audio/") ||
        mime === "application/pdf" ||
        mime.startsWith("text/")
    ) {
        openPreview(item);
    } else {
        downloadFile(path);
    }
}

window.openItem = openItem;


// ============================================================
// CONTEXT MENU
// ============================================================

function openContextMenu(event, path) {
    event.preventDefault();
    event.stopPropagation();

    state.selected = path;

    contextMenu.style.display = "block";

    const menuWidth = 170;
    const menuHeight = 240;

    const x = Math.min(
        event.clientX,
        window.innerWidth - menuWidth - 8
    );

    const y = Math.min(
        event.clientY,
        window.innerHeight - menuHeight - 8
    );

    contextMenu.style.left = `${x}px`;
    contextMenu.style.top = `${y}px`;
}

window.openContextMenu =
    openContextMenu;

document.addEventListener(
    "click",
    () => {
        contextMenu.style.display = "none";
    }
);

contextMenu.addEventListener(
    "click",
    async (event) => {
        const action =
            event.target.dataset.action;

        if (!action || !state.selected) {
            return;
        }

        contextMenu.style.display = "none";

        const item = state.items.find(
            x => x.path === state.selected
        );

        if (!item) return;

        try {
            if (action === "open") {
                openItem(
                    item.path,
                    item.is_dir
                );
            }

            if (action === "download") {
                downloadFile(item.path);
            }

            if (action === "rename") {
                renameItem(item);
            }

            if (action === "move") {
                moveItem(item);
            }

            if (action === "delete") {
                deleteItem(item);
            }

            if (action === "properties") {
                propertiesItem(item);
            }

        } catch (error) {
            showToast(
                error.message,
                true
            );
        }
    }
);


// ============================================================
// DOWNLOAD
// ============================================================

function downloadFile(path) {
    const url =
        `/api/download?path=${encodeURIComponent(path)}`;

    const link =
        document.createElement("a");

    link.href = url;
    link.download = "";

    document.body.appendChild(link);

    link.click();

    link.remove();
}


// ============================================================
// PREVIEW
// ============================================================

function openPreview(item) {
    const url =
        `/api/preview?path=${encodeURIComponent(item.path)}`;

    let content = "";

    if (item.type.startsWith("image/")) {
        content = `
            <img
                src="${url}"
                class="preview-image"
                alt=""
            >
        `;
    } else if (item.type.startsWith("video/")) {
        content = `
            <video
                class="preview-video"
                controls
                autoplay
            >
                <source src="${url}">
            </video>
        `;
    } else if (item.type.startsWith("audio/")) {
        content = `
            <audio
                class="preview-audio"
                controls
                autoplay
            >
                <source src="${url}">
            </audio>
        `;
    } else if (
        item.type === "application/pdf"
    ) {
        content = `
            <iframe
                class="preview-frame"
                src="${url}"
            ></iframe>
        `;
    } else {
        content = `
            <iframe
                class="preview-frame"
                src="${url}"
            ></iframe>
        `;
    }

    showModal(`
        <div class="modal-title">
            ${escapeHtml(item.name)}
        </div>

        <div class="modal-subtitle">
            ${escapeHtml(item.type)}
            •
            ${formatBytes(item.size)}
        </div>

        ${content}

        <div class="modal-actions">

            <button
                class="button secondary"
                onclick="closeModal()"
            >
                CLOSE
            </button>

            <button
                class="button primary"
                onclick="downloadFile('${escapeHtml(item.path)}')"
            >
                DOWNLOAD
            </button>

        </div>
    `);
}

window.downloadFile =
    downloadFile;


// ============================================================
// NEW FOLDER
// ============================================================

$("#new-folder").addEventListener(
    "click",
    () => {

        showModal(`
            <div class="modal-title">
                CREATE FOLDER
            </div>

            <div class="modal-subtitle">
                /${escapeHtml(state.currentPath)}
            </div>

            <input
                id="modal-folder-name"
                class="modal-input"
                placeholder="Folder name"
                autofocus
            >

            <div class="modal-actions">

                <button
                    class="button secondary"
                    onclick="closeModal()"
                >
                    CANCEL
                </button>

                <button
                    class="button primary"
                    id="create-folder-submit"
                >
                    CREATE
                </button>

            </div>
        `);

        $("#create-folder-submit")
            .addEventListener(
                "click",
                createFolder
            );
    }
);

async function createFolder() {
    const input =
        $("#modal-folder-name");

    const name = input.value.trim();

    if (!name) return;

    try {
        await api(
            "/api/folder",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    parent:
                        state.currentPath,
                    name,
                }),
            }
        );

        closeModal();

        showToast(
            "Folder created"
        );

        await loadDirectory(
            state.currentPath
        );

        refreshStorage();

    } catch (error) {
        showToast(
            error.message,
            true
        );
    }
}


// ============================================================
// RENAME
// ============================================================

function renameItem(item) {
    showModal(`
        <div class="modal-title">
            RENAME
        </div>

        <div class="modal-subtitle">
            ${escapeHtml(item.path)}
        </div>

        <input
            id="modal-rename"
            class="modal-input"
            value="${escapeHtml(item.name)}"
        >

        <div class="modal-actions">

            <button
                class="button secondary"
                onclick="closeModal()"
            >
                CANCEL
            </button>

            <button
                class="button primary"
                id="rename-submit"
            >
                RENAME
            </button>

        </div>
    `);

    $("#rename-submit")
        .addEventListener(
            "click",
            async () => {

                const newName =
                    $("#modal-rename")
                        .value
                        .trim();

                if (!newName) return;

                try {
                    await api(
                        "/api/rename",
                        {
                            method: "PATCH",
                            headers: {
                                "Content-Type":
                                    "application/json"
                            },
                            body: JSON.stringify({
                                path: item.path,
                                new_name: newName,
                            }),
                        }
                    );

                    closeModal();

                    showToast(
                        "Renamed successfully"
                    );

                    await loadDirectory(
                        state.currentPath
                    );

                } catch (error) {
                    showToast(
                        error.message,
                        true
                    );
                }
            }
        );
}


// ============================================================
// MOVE
// ============================================================

function moveItem(item) {
    showModal(`
        <div class="modal-title">
            MOVE
        </div>

        <div class="modal-subtitle">
            ${escapeHtml(item.name)}
        </div>

        <input
            id="modal-move"
            class="modal-input"
            value="${escapeHtml(state.currentPath)}"
            placeholder="Destination folder"
        >

        <div class="modal-subtitle">
            Example: Foto Vian/Liburan
        </div>

        <div class="modal-actions">

            <button
                class="button secondary"
                onclick="closeModal()"
            >
                CANCEL
            </button>

            <button
                class="button primary"
                id="move-submit"
            >
                MOVE
            </button>

        </div>
    `);

    $("#move-submit")
        .addEventListener(
            "click",
            async () => {

                const destination =
                    $("#modal-move")
                        .value
                        .trim();

                try {
                    await api(
                        "/api/move",
                        {
                            method: "POST",
                            headers: {
                                "Content-Type":
                                    "application/json"
                            },
                            body: JSON.stringify({
                                source: item.path,
                                destination,
                            }),
                        }
                    );

                    closeModal();

                    showToast(
                        "Moved successfully"
                    );

                    await loadDirectory(
                        state.currentPath
                    );

                } catch (error) {
                    showToast(
                        error.message,
                        true
                    );
                }
            }
        );
}


// ============================================================
// DELETE
// ============================================================

function deleteItem(item) {
    const warning =
        item.is_dir
            ? "This folder and all of its contents will be permanently deleted."
            : "This file will be permanently deleted.";

    showModal(`
        <div class="modal-title">
            DELETE "${escapeHtml(item.name)}"?
        </div>

        <div class="modal-subtitle">
            This action cannot be undone.
        </div>

        <div class="confirm-warning">
            ${warning}
        </div>

        <div class="modal-actions">

            <button
                class="button secondary"
                onclick="closeModal()"
            >
                CANCEL
            </button>

            <button
                class="button danger-button"
                id="delete-submit"
            >
                DELETE
            </button>

        </div>
    `);

    $("#delete-submit")
        .addEventListener(
            "click",
            async () => {

                try {
                    await api(
                        "/api/delete",
                        {
                            method: "DELETE",
                            headers: {
                                "Content-Type":
                                    "application/json"
                            },
                            body: JSON.stringify({
                                path: item.path,
                            }),
                        }
                    );

                    closeModal();

                    showToast(
                        "Deleted successfully"
                    );

                    await loadDirectory(
                        state.currentPath
                    );

                    refreshStorage();

                } catch (error) {
                    showToast(
                        error.message,
                        true
                    );
                }
            }
        );
}


// ============================================================
// PROPERTIES
// ============================================================

async function propertiesItem(item) {
    try {
        const data = await api(
            `/api/properties?path=${encodeURIComponent(item.path)}`
        );

        let extra = "";

        if (data.is_dir) {
            extra = `
                <div class="label">Files</div>
                <div class="value">
                    ${data.files}
                </div>

                <div class="label">Folders</div>
                <div class="value">
                    ${data.folders}
                </div>

                <div class="label">Total Size</div>
                <div class="value">
                    ${formatBytes(data.total_size)}
                </div>
            `;
        } else {
            extra = `
                <div class="label">Size</div>
                <div class="value">
                    ${formatBytes(data.size)}
                </div>
            `;
        }

        showModal(`
            <div class="modal-title">
                ${escapeHtml(data.name)}
            </div>

            <div class="modal-subtitle">
                FILE INFORMATION
            </div>

            <div class="modal-info">

                <div class="label">Type</div>
                <div class="value">
                    ${escapeHtml(data.type)}
                </div>

                <div class="label">Location</div>
                <div class="value">
                    /${escapeHtml(data.path)}
                </div>

                ${extra}

                <div class="label">Created</div>
                <div class="value">
                    ${formatDate(data.created)}
                </div>

                <div class="label">Modified</div>
                <div class="value">
                    ${formatDate(data.modified)}
                </div>

            </div>

            <div class="modal-actions">

                <button
                    class="button secondary"
                    onclick="closeModal()"
                >
                    CLOSE
                </button>

            </div>
        `);

    } catch (error) {
        showToast(
            error.message,
            true
        );
    }
}


// ============================================================
// UPLOAD
// ============================================================

$("#upload-button")
    .addEventListener(
        "click",
        () => {
            $("#file-input").click();
        }
    );

$("#file-input")
    .addEventListener(
        "change",
        async (event) => {

            const files =
                Array.from(
                    event.target.files
                );

            for (const file of files) {
                uploadFile(file);
            }

            event.target.value = "";
        }
    );


async function uploadFile(file) {
    const chunkSize = 16 * 1024 * 1024;

    try {

        const init = await api(
            "/api/upload/init",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    filename: file.name,
                    path: state.currentPath,
                    size: file.size,
                }),
            }
        );

        const uploadId =
            init.upload_id;

        const totalChunks =
            init.total_chunks;

        const stored =
            await api(
                `/api/upload/status?upload_id=${uploadId}`
            );

        const received =
            new Set(
                stored.received_chunks
            );

        let uploaded =
            received.size;

        for (
            let index = 0;
            index < totalChunks;
            index++
        ) {

            if (received.has(index)) {
                continue;
            }

            const start =
                index * chunkSize;

            const end =
                Math.min(
                    start + chunkSize,
                    file.size
                );

            const chunk =
                file.slice(
                    start,
                    end
                );

            const form =
                new FormData();

            form.append(
                "upload_id",
                uploadId
            );

            form.append(
                "chunk_index",
                String(index)
            );

            form.append(
                "file",
                chunk,
                file.name
            );

            await api(
                "/api/upload/chunk",
                {
                    method: "POST",
                    body: form,
                }
            );

            uploaded++;

            const percentage =
                Math.round(
                    uploaded /
                    totalChunks *
                    100
                );

            showToast(
                `Uploading ${file.name}: ${percentage}%`
            );
        }

        await api(
            "/api/upload/complete",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    upload_id: uploadId,
                }),
            }
        );

        showToast(
            `Upload complete: ${file.name}`
        );

        await loadDirectory(
            state.currentPath
        );

        refreshStorage();

    } catch (error) {
        showToast(
            `Upload failed: ${error.message}`,
            true
        );
    }
}


// ============================================================
// SEARCH
// ============================================================

let searchTimer = null;

$("#search-input")
    .addEventListener(
        "input",
        () => {

            clearTimeout(
                searchTimer
            );

            const query =
                $("#search-input")
                    .value
                    .trim();

            if (!query) {
                loadDirectory(
                    state.currentPath
                );

                return;
            }

            searchTimer =
                setTimeout(
                    () => search(query),
                    250
                );
        }
    );

async function search(query) {
    try {
        state.searchMode = true;

        const data = await api(
            `/api/search?q=${encodeURIComponent(query)}`
        );

        state.items =
            data.results;

        breadcrumb.innerHTML = `
            <span>
                SEARCH / ${escapeHtml(query)}
            </span>
        `;

        renderFiles();

    } catch (error) {
        showToast(
            error.message,
            true
        );
    }
}


// ============================================================
// STORAGE
// ============================================================

async function refreshStorage() {
    try {
        const data =
            await api("/api/storage");

        $("#storage-value")
            .textContent =
            `${formatBytes(data.used)} / ${formatBytes(data.total)}`;

        $("#storage-used")
            .textContent =
            formatBytes(data.used);

        $("#storage-free")
            .textContent =
            formatBytes(data.free);

        $("#storage-progress")
            .style.width =
            `${data.percentage}%`;

    } catch (error) {
        console.error(error);
    }
}


// ============================================================
// UP
// ============================================================

$("#up-button")
    .addEventListener(
        "click",
        () => {
            if (state.searchMode) {
                loadDirectory("");
                return;
            }

            loadDirectory(
                pathParent(
                    state.currentPath
                )
            );
        }
    );


// ============================================================
// VIEW
// ============================================================

$("#list-view")
    .addEventListener(
        "click",
        () => {
            state.view = "list";

            $("#list-view")
                .classList.add("active");

            $("#grid-view")
                .classList.remove("active");

            renderFiles();
        }
    );

$("#grid-view")
    .addEventListener(
    "click",
    () => {
        state.view = "grid";

        $("#grid-view")
            .classList.add("active");

        $("#list-view")
            .classList.remove("active");

        renderFiles();
    }
);


// ============================================================
// REFRESH
// ============================================================

$("#refresh-btn")
    .addEventListener(
        "click",
        async () => {
            await loadDirectory(
                state.currentPath
            );

            await refreshStorage();
        }
    );


// ============================================================
// MODAL
// ============================================================

function showModal(html) {
    modal.innerHTML = html;

    modalBackdrop.classList.add(
        "show"
    );
}

function closeModal() {
    modalBackdrop.classList.remove(
        "show"
    );

    modal.innerHTML = "";
}

window.closeModal =
    closeModal;

modalBackdrop.addEventListener(
    "click",
    (event) => {
        if (
            event.target ===
            modalBackdrop
        ) {
            closeModal();
        }
    }
);


// ============================================================
// MOBILE SIDEBAR
// ============================================================

$("#mobile-menu")
    .addEventListener(
        "click",
        () => {
            $("#sidebar")
                .classList.toggle(
                    "open"
                );
        }
    );


// ============================================================
// KEYBOARD SHORTCUT
// ============================================================

document.addEventListener(
    "keydown",
    (event) => {

        if (
            event.key === "/" &&
            document.activeElement.tagName !== "INPUT"
        ) {
            event.preventDefault();

            $("#search-input")
                .focus();
        }

        if (
            event.key === "Escape"
        ) {
            closeModal();

            contextMenu.style.display =
                "none";
        }
    }
);
// ============================================================
// SIDEBAR NAVIGATION
// ============================================================

const navFiles = $("#nav-files");
const navRecent = $("#nav-recent");
const navActivity = $("#nav-activity");
const navStorage = $("#nav-storage");

const systemView = $("#system-view");

function setActiveNav(activeButton) {
    document
        .querySelectorAll(".nav-item")
        .forEach((button) => {
            button.classList.remove("active");
        });

    activeButton.classList.add("active");
}

function showFilesView() {
    systemView.hidden = true;
    fileList.style.display = "";
    $(".toolbar").style.display = "";
    $(".storage-panel").style.display = "";
    $(".search-bar").style.display = "";
    $(".page-head").style.display = "";

    setActiveNav(navFiles);

    loadDirectory(state.currentPath);
}

function showSystemView() {
    fileList.style.display = "none";
    $(".toolbar").style.display = "none";
    $(".storage-panel").style.display = "none";
    $(".search-bar").style.display = "none";
    $(".page-head").style.display = "none";

    systemView.hidden = false;
}

navFiles.addEventListener(
    "click",
    () => {
        showFilesView();
    }
);

navRecent.addEventListener(
    "click",
    async () => {
        setActiveNav(navRecent);
        showSystemView();

        await renderRecent();
    }
);

navActivity.addEventListener(
    "click",
    async () => {
        setActiveNav(navActivity);
        showSystemView();

        await renderActivity();
    }
);

navStorage.addEventListener(
    "click",
    async () => {
        setActiveNav(navStorage);
        showSystemView();

        await renderStoragePage();
    }
);
// ============================================================
// RECENT
// ============================================================

async function renderRecent() {
    systemView.innerHTML = `
        <div class="system-header">

            <div>
                <div class="eyebrow">
                    STORAGE / RECENT
                </div>

                <h2>RECENT FILES</h2>

                <div class="system-description">
                    Files and folders most recently modified
                    on the filesystem.
                </div>
            </div>

            <button
                class="button secondary"
                id="recent-refresh"
            >
                ↻ REFRESH
            </button>

        </div>

        <div id="recent-content">
            <div class="system-empty">
                LOADING...
            </div>
        </div>
    `;

    $("#recent-refresh").addEventListener(
        "click",
        renderRecent
    );

    try {
        /*
         * We intentionally get the filesystem tree directly.
         * No database/index is required.
         */
        const data = await api(
            "/api/search?q=."
        );

        let items = data.results || [];

        /*
         * The search endpoint is designed for name search,
         * so filter it here and sort using modified timestamps.
         */
        items = items
            .filter(item => item.name)
            .sort(
                (a, b) =>
                    new Date(b.modified) -
                    new Date(a.modified)
            )
            .slice(0, 30);

        if (!items.length) {
            $("#recent-content").innerHTML = `
                <div class="system-empty">
                    NO RECENT FILES
                </div>
            `;

            return;
        }

        $("#recent-content").innerHTML = `
            <table class="system-table">

                <thead>
                    <tr>
                        <th>ITEM</th>
                        <th>TYPE</th>
                        <th>SIZE</th>
                        <th>MODIFIED</th>
                        <th></th>
                    </tr>
                </thead>

                <tbody>
                    ${items.map(item => `
                        <tr>

                            <td>
                                <div style="
                                    display:flex;
                                    align-items:center;
                                    gap:11px;
                                ">

                                    <div class="recent-icon">
                                        ${iconFor(item)}
                                    </div>

                                    <div>
                                        <div class="recent-name">
                                            ${escapeHtml(item.name)}
                                        </div>

                                        <div class="recent-location">
                                            /${escapeHtml(item.path)}
                                        </div>
                                    </div>

                                </div>
                            </td>

                            <td>
                                ${escapeHtml(item.type)}
                            </td>

                            <td>
                                ${
                                    item.is_dir
                                        ? "DIRECTORY"
                                        : formatBytes(item.size)
                                }
                            </td>

                            <td>
                                ${formatDate(item.modified)}
                            </td>

                            <td>
                                <button
                                    class="toolbar-button"
                                    onclick="openItem(
                                        '${escapeHtml(item.path)}',
                                        ${item.is_dir}
                                    )"
                                >
                                    OPEN
                                </button>
                            </td>

                        </tr>
                    `).join("")}
                </tbody>

            </table>
        `;

    } catch (error) {
        $("#recent-content").innerHTML = `
            <div class="system-empty">
                FAILED TO LOAD RECENT FILES
            </div>
        `;

        showToast(
            error.message,
            true
        );
    }
}

// ============================================================
// INIT
// ============================================================

async function init() {

    try {
        const health =
            await api("/api/health");

        $("#storage-path")
            .textContent =
            health.storage_path;

    } catch (error) {
        showToast(
            `Backend unavailable: ${error.message}`,
            true
        );
    }

    await loadDirectory("");

    await refreshStorage();
}

init();
