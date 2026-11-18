from __future__ import annotations

import itertools
import os
import time
from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from fastapi.responses import RedirectResponse
from nicegui import app, events, ui

API_BASE = os.environ.get("API_URL", "http://localhost:8000")
STORAGE_SECRET = os.environ.get("UI_STORAGE_SECRET", "local-dev-only")

# The invitation mail links to /join?token=...; the token waits here until the user is logged in.
JOIN_TOKEN_KEY = "join_token"

UPLOAD_PATH = "/project/{project_id}/documents"
UPLOAD_FIELD = "files"
REPLACE_FIELD = "file"
UPLOAD_ACCEPT = ".pdf,.docx"
# The API checks the real project total; this only stops a single oversized pick early.
UPLOAD_MAX_TOTAL_SIZE = 50 * 1024 * 1024

# The API serves only PDFs inline, so only PDFs get a preview; DOCX downloads.
PDF = "application/pdf"

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
    '&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">'
)

THEME_CSS = """
body { font-family: 'Inter', system-ui, sans-serif; background: #fafafa; color: #09090b; }
code, .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.8rem; }
.q-card { box-shadow: none !important; border: 1px solid #e4e4e7; border-radius: 12px; }
.q-btn { border-radius: 8px; text-transform: none; font-weight: 500; letter-spacing: 0; }
.q-field--outlined .q-field__control { border-radius: 8px; }
.q-field--outlined .q-field__control:before { border-color: #e4e4e7; }
.q-header { border-bottom: 1px solid #e4e4e7; }
.q-drawer { background: #fafafa !important; }
.q-tab { text-transform: none; font-weight: 500; }
.q-chip { border-radius: 6px; }
.q-chip--outline { border-color: #e4e4e7 !important; color: #52525b !important; }
.q-uploader { box-shadow: none; border: 1px dashed #d4d4d8 !important; border-radius: 10px; }
.q-uploader__header { background: #fafafa !important; color: #09090b !important; }
.q-notification { border-radius: 10px; }
.q-table th { font-weight: 600; color: #71717a; }
.auth-aside { display: none !important; }
@media (min-width: 1024px) { .auth-aside { display: flex !important; } }
@media (min-width: 1024px) { .auth-mobile-brand { display: none !important; } }
"""


async def api_call(
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    auth: bool = False,
    params: dict[str, str] | None = None,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
) -> httpx.Response:
    headers: dict[str, str] = {}
    token = app.storage.user.get("token")
    if auth and token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
        return await client.request(
            method, path, json=json_body, headers=headers, params=params, files=files
        )


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except ValueError:
            return exc.response.text
        if isinstance(detail, list):
            return "; ".join(
                f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg', '')}"
                for d in detail
            )
        return str(detail)
    if isinstance(exc, httpx.ConnectError):
        return f"Cannot reach the API at {API_BASE}"
    return str(exc) or exc.__class__.__name__


def error_status(exc: Exception) -> int | None:
    return exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None


def status_label(status: int | None) -> str:
    if status is None:
        return "No response"
    try:
        return f"{status} {HTTPStatus(status).phrase}"
    except ValueError:
        return str(status)


def notify_ok(message: str, status: int) -> None:
    ui.notify(message, type="positive", caption=status_label(status))


def notify_error(exc: Exception) -> None:
    ui.notify(error_text(exc), type="negative", caption=status_label(error_status(exc)))


def day(value: str) -> str:
    return value[:10]


def file_icon(content_type: str) -> str:
    return "picture_as_pdf" if content_type == PDF else "article"


def size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{max(size // 1024, 1)} KB"


def brand(dark: bool = False) -> None:
    mark = "bg-white text-zinc-950" if dark else "bg-zinc-950 text-white"
    with ui.row().classes("items-center gap-2 no-wrap"):
        ui.label("P").classes(
            f"{mark} w-8 h-8 rounded-lg flex items-center justify-center font-bold"
        )
        ui.label("Projects").classes("text-lg font-semibold tracking-tight")


@ui.page("/")
def index() -> None:
    ui.colors(
        primary="#09090b",
        secondary="#52525b",
        positive="#16a34a",
        negative="#dc2626",
        warning="#d97706",
        info="#52525b",
    )
    ui.add_head_html(FONTS)
    ui.add_css(THEME_CSS)
    ui.query(".nicegui-content").classes("p-0 gap-0")

    view = {"page": "projects", "query": ""}
    projects: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    call_ids = itertools.count(1)

    def logged_in() -> bool:
        return bool(app.storage.user.get("token"))

    def apply_state() -> None:
        header.set_visibility(logged_in())
        drawer.set_visibility(logged_in())
        drawer.value = logged_in()
        mark_nav()
        if logged_in():
            username = app.storage.user.get("user", "")
            avatar_label.set_text(username[:1].upper())
            user_label.set_text(username)
        content.refresh()

    # ------------------------------------------------------------- requests
    def record(method: str, path: str, status: int | None, started: float) -> None:
        calls.insert(
            0,
            {
                "id": next(call_ids),
                "time": datetime.now().strftime("%H:%M:%S"),
                "method": method,
                "path": path,
                "status": status or 0,
                "label": status_label(status),
                "ms": round((time.perf_counter() - started) * 1000),
            },
        )
        del calls[100:]
        activity_table.refresh()

    async def request(
        method: str, path: str, *, log: bool = True, **kwargs: Any
    ) -> tuple[int, Any]:
        started = time.perf_counter()
        try:
            response = await api_call(method, path, **kwargs)
        except httpx.HTTPError:
            if log:
                record(method, path, None, started)
            raise
        if log:
            record(method, path, response.status_code, started)
        if response.is_redirect:
            return response.status_code, response.headers["location"]
        response.raise_for_status()
        return response.status_code, response.json() if response.content else None

    # ---------------------------------------------------------------- auth
    async def register_user(login: str, password: str, repeat: str) -> bool:
        payload = {"login": login, "password": password, "repeat_password": repeat}
        try:
            status, _ = await request("POST", "/auth", json_body=payload)
        except httpx.HTTPError as exc:
            notify_error(exc)
            return False
        notify_ok("Account created, signing you in", status)
        return True

    async def login_user(login: str, password: str) -> None:
        try:
            _, data = await request(
                "POST", "/login", json_body={"login": login, "password": password}
            )
        except httpx.HTTPError as exc:
            notify_error(exc)
            return
        app.storage.user["token"] = data["access_token"]
        app.storage.user["user"] = login
        view["page"] = "projects"
        await load_projects()
        apply_state()
        # apply_state() removed the login form this handler belongs to; run in a lasting element
        with dialog_host:
            await join_pending()

    def logout() -> None:
        app.storage.user.clear()
        projects.clear()
        apply_state()
        ui.notify("Signed out", type="info")

    def auth_view() -> None:
        async def do_login() -> None:
            login_btn.props("loading")
            await login_user(login_login.value, login_pass.value)
            login_btn.props(remove="loading")

        async def do_register() -> None:
            reg_btn.props("loading")
            if await register_user(reg_login.value, reg_pass.value, reg_repeat.value):
                await login_user(reg_login.value, reg_pass.value)
            reg_btn.props(remove="loading")

        with ui.element("div").classes("w-full grid lg:grid-cols-2").style("min-height:100vh"):
            with ui.column().classes("auth-aside bg-zinc-950 text-white p-12 justify-between"):
                brand(dark=True)
                with ui.column().classes("gap-4 max-w-md"):
                    ui.label("Projects app.").classes(
                        "text-4xl font-semibold tracking-tight leading-tight"
                    )
                    ui.label(
                        "Create projects, invite your team and keep every file where it belongs."
                    ).classes("text-zinc-400")
                ui.label(f"API · {API_BASE}").classes("mono text-zinc-500")
            with (
                ui.column().classes("items-center justify-center p-6 bg-white"),
                ui.column().classes("w-full max-w-sm gap-6"),
            ):
                with ui.element("div").classes("auth-mobile-brand"):
                    brand()
                with ui.column().classes("gap-1"):
                    ui.label("Welcome").classes("text-2xl font-semibold tracking-tight")
                    ui.label("Sign in or create an account to continue.").classes(
                        "text-zinc-500 text-sm"
                    )
                if app.storage.user.get(JOIN_TOKEN_KEY):
                    with ui.row().classes(
                        "w-full items-center gap-3 no-wrap p-3 rounded-lg "
                        "border border-zinc-200 bg-zinc-50"
                    ):
                        ui.icon("mail", color="grey-8")
                        ui.label(
                            "You've been invited to a project. Sign in or create an account "
                            "and you'll join it right away."
                        ).classes("text-sm text-zinc-700")
                with (
                    ui.tabs()
                    .props("align=left dense no-caps")
                    .classes("w-full border-b border-zinc-200") as tabs
                ):
                    ui.tab("login", "Sign in")
                    ui.tab("register", "Create account")
                with ui.tab_panels(tabs, value="login").classes("w-full"):
                    with ui.tab_panel("login").classes("gap-3 p-0 pt-4"):
                        login_login = ui.input("Login").props("outlined").classes("w-full")
                        login_pass = (
                            ui.input("Password", password=True, password_toggle_button=True)
                            .props("outlined")
                            .classes("w-full")
                        )
                        login_pass.on("keydown.enter", do_login)
                        login_btn = (
                            ui.button("Sign in", on_click=do_login)
                            .classes("w-full")
                            .props("unelevated")
                            .classes("h-11")
                        )
                    with ui.tab_panel("register").classes("gap-3 p-0 pt-4"):
                        reg_login = ui.input("Login").props("outlined").classes("w-full")
                        reg_pass = (
                            ui.input("Password", password=True, password_toggle_button=True)
                            .props("outlined")
                            .classes("w-full")
                        )
                        reg_repeat = (
                            ui.input("Repeat password", password=True)
                            .props("outlined")
                            .classes("w-full")
                        )
                        reg_repeat.on("keydown.enter", do_register)
                        reg_btn = (
                            ui.button("Create account", on_click=do_register)
                            .classes("w-full")
                            .props("unelevated")
                            .classes("h-11")
                        )

    # ------------------------------------------------------------ projects
    async def load_projects() -> None:
        try:
            _, rows = await request("GET", "/projects", auth=True)
        except httpx.HTTPError as exc:
            notify_error(exc)
            return
        projects[:] = rows

    async def reload_view() -> None:
        await load_projects()
        content.refresh()

    def new_project_dialog() -> None:
        async def create() -> None:
            payload = {"name": name.value, "description": desc.value or None}
            try:
                status, _ = await request("POST", "/projects", json_body=payload, auth=True)
            except httpx.HTTPError as exc:
                notify_error(exc)
                return
            dialog.close()
            notify_ok("Project created", status)
            await reload_view()

        with dialog_host, ui.dialog() as dialog, ui.card().classes("w-96 p-6 gap-3"):
            ui.label("New project").classes("text-xl font-semibold")
            name = ui.input("Name").props("outlined autofocus").classes("w-full")
            desc = ui.textarea("Description").props("outlined").classes("w-full")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Create", on_click=create).props("unelevated")
        dialog.open()

    async def project_dialog(project_id: str) -> None:
        try:
            info_status, info = await request("GET", f"/project/{project_id}/info", auth=True)
        except httpx.HTTPError as exc:
            notify_error(exc)
            return

        async def invite() -> None:
            login = invite_input.value
            if not login:
                ui.notify("Enter a login to invite", type="warning")
                return
            try:
                status, _ = await request(
                    "POST", f"/project/{project_id}/invite", auth=True, params={"user": login}
                )
            except httpx.HTTPError as exc:
                notify_error(exc)
                return
            invite_input.set_value("")
            notify_ok(f"{login} added to the project", status)

        async def share() -> None:
            email = email_input.value
            if not email:
                ui.notify("Enter an email to invite", type="warning")
                return
            try:
                status, invitation = await request(
                    "POST", f"/project/{project_id}/share", auth=True, params={"with": email}
                )
            except httpx.HTTPError as exc:
                notify_error(exc)
                return
            email_input.set_value("")
            expires = invitation["expires_at"][:16].replace("T", " ")
            notify_ok(
                f"Invitation sent to {invitation['email']}, valid until {expires} UTC", status
            )

        async def upload(e: events.MultiUploadEventArguments) -> None:
            files = [
                (
                    UPLOAD_FIELD,
                    (f.name, await f.read(), f.content_type or "application/octet-stream"),
                )
                for f in e.files
            ]
            try:
                status, docs = await request(
                    "POST", UPLOAD_PATH.format(project_id=project_id), auth=True, files=files
                )
            except httpx.HTTPError as exc:
                notify_error(exc)
                uploader.reset()
                return
            uploader.reset()
            notify_ok(f"Uploaded {len(docs)} file(s)", status)
            await refresh_documents()

        async def refresh_documents() -> None:
            try:
                _, rows = await request("GET", f"/project/{project_id}/documents", auth=True)
            except httpx.HTTPError as exc:
                notify_error(exc)
                return
            documents[:] = rows
            document_list.refresh()
            await reload_view()

        def replace_dialog(doc: dict[str, Any]) -> None:
            async def replace(e: events.UploadEventArguments) -> None:
                file = (e.file.name, await e.file.read(), e.file.content_type)
                try:
                    status, updated = await request(
                        "PUT", f"/document/{doc['id']}", auth=True, files=[(REPLACE_FIELD, file)]
                    )
                except httpx.HTTPError as exc:
                    notify_error(exc)
                    picker.reset()
                    return
                box.close()
                notify_ok(f"Replaced with {updated['filename']}", status)
                await refresh_documents()

            with dialog_host, ui.dialog() as box, ui.card().classes("w-96 p-6 gap-3"):
                ui.label("Replace document").classes("text-xl font-semibold")
                ui.label(
                    f"Pick a PDF or DOCX to replace {doc['filename']}. The old file is deleted."
                ).classes("text-zinc-600 text-sm")
                picker = (
                    ui.upload(
                        on_upload=replace,
                        auto_upload=True,
                        max_total_size=UPLOAD_MAX_TOTAL_SIZE,
                        on_rejected=rejected,
                        label="PDF or DOCX",
                    )
                    .props(f'accept="{UPLOAD_ACCEPT}" flat bordered')
                    .classes("w-full")
                )
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=box.close).props("flat")
            box.on("hide", box.delete)
            box.open()

        def delete_document_dialog(doc: dict[str, Any]) -> None:
            async def delete() -> None:
                try:
                    status, _ = await request("DELETE", f"/document/{doc['id']}", auth=True)
                except httpx.HTTPError as exc:
                    notify_error(exc)
                    return
                box.close()
                notify_ok(f"Deleted {doc['filename']}", status)
                await refresh_documents()

            with dialog_host, ui.dialog() as box, ui.card().classes("w-96 p-6 gap-3"):
                ui.label("Delete document?").classes("text-xl font-semibold")
                ui.label(f"{doc['filename']} will be removed. This cannot be undone.").classes(
                    "text-zinc-600 text-sm"
                )
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=box.close).props("flat")
                    ui.button("Delete", on_click=delete).props("unelevated color=negative")
            box.on("hide", box.delete)
            box.open()

        def edit_dialog() -> None:
            async def save() -> None:
                payload = {"name": name.value, "description": desc.value or None}
                try:
                    status, updated = await request(
                        "PUT", f"/project/{project_id}/info", json_body=payload, auth=True
                    )
                except httpx.HTTPError as exc:
                    notify_error(exc)
                    return
                info.update(updated)
                name_label.set_text(updated["name"])
                desc_label.set_text(updated["description"] or "No description")
                updated_chip.set_text(f"Updated {day(updated['updated_at'])}")
                edit.close()
                notify_ok("Project updated", status)
                await reload_view()

            with dialog_host, ui.dialog() as edit, ui.card().classes("w-96 p-6 gap-3"):
                ui.label("Edit project").classes("text-xl font-semibold")
                name = ui.input("Name", value=info["name"]).props("outlined").classes("w-full")
                desc = (
                    ui.textarea("Description", value=info["description"] or "")
                    .props("outlined")
                    .classes("w-full")
                )
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=edit.close).props("flat")
                    ui.button("Save", on_click=save).props("unelevated")
            edit.open()

        def delete_dialog() -> None:
            async def delete() -> None:
                try:
                    status, _ = await request("DELETE", f"/project/{project_id}", auth=True)
                except httpx.HTTPError as exc:
                    notify_error(exc)
                    return
                confirm.close()
                dialog.close()
                notify_ok(f"Deleted {info['name']}", status)
                await reload_view()

            with dialog_host, ui.dialog() as confirm, ui.card().classes("w-96 p-6 gap-3"):
                ui.label("Delete project?").classes("text-xl font-semibold")
                ui.label(
                    f"{info['name']} and all its documents will be removed. This cannot be undone."
                ).classes("text-zinc-600 text-sm")
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=confirm.close).props("flat")
                    ui.button("Delete", on_click=delete).props("unelevated color=negative")
            confirm.open()

        async def open_document(doc: dict[str, Any]) -> None:
            try:
                status, url = await request("GET", f"/document/{doc['id']}", auth=True)
            except httpx.HTTPError as exc:
                notify_error(exc)
                return
            if doc["content_type"] != PDF:
                ui.navigate.to(url)
                notify_ok(f"Downloading {doc['filename']}", status)
                return
            with (
                dialog_host,
                ui.dialog() as preview,
                ui.card().classes("p-0 gap-0 w-[min(92vw,1000px)] max-w-none h-[88vh]"),
            ):
                with ui.row().classes(
                    "w-full items-center justify-between no-wrap px-4 py-3 border-b border-zinc-200"
                ):
                    with ui.row().classes("items-center gap-2 no-wrap min-w-0"):
                        ui.icon(file_icon(doc["content_type"]), color="grey-8")
                        ui.label(doc["filename"]).classes("font-semibold truncate")
                        ui.label(status_label(status)).classes("mono text-xs text-zinc-400")
                    with ui.row().classes("gap-1 no-wrap"):
                        ui.button(
                            "Open in new tab",
                            icon="open_in_new",
                            on_click=lambda: ui.navigate.to(url, new_tab=True),
                        ).props("flat dense color=grey-8")
                        ui.button(icon="close", on_click=preview.close).props(
                            "flat round dense color=grey-7"
                        )
                frame = ui.element("iframe").classes("w-full grow border-0 bg-white")
                frame.props["src"] = url
            preview.on("hide", preview.delete)
            preview.open()

        def rejected() -> None:
            ui.notify(
                f"Uploads are limited to {size_text(UPLOAD_MAX_TOTAL_SIZE)} per project",
                type="warning",
            )

        documents: list[dict[str, Any]] = list(
            next((p["documents"] for p in projects if p["id"] == project_id), [])
        )

        @ui.refreshable
        def document_list() -> None:
            if not documents:
                ui.label("No documents yet").classes("text-zinc-400 text-sm")
            for doc in documents:
                is_pdf = doc["content_type"] == PDF
                with ui.row().classes(
                    "w-full items-center gap-1 no-wrap pl-3 pr-1 py-1 rounded-lg "
                    "hover:bg-zinc-100 transition-colors"
                ):
                    with (
                        ui.row()
                        .classes("items-center gap-3 no-wrap grow min-w-0 cursor-pointer py-1")
                        .on("click", lambda d=doc: open_document(d))
                    ):
                        ui.icon(file_icon(doc["content_type"]), color="grey-8")
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(doc["filename"]).classes("text-sm font-medium truncate")
                            ui.label(
                                f"{size_text(doc['size_bytes'])} · {day(doc['created_at'])}"
                            ).classes("text-xs text-zinc-400")
                    ui.button(
                        icon="visibility" if is_pdf else "download",
                        on_click=lambda d=doc: open_document(d),
                    ).props("flat round dense size=sm color=grey-7").tooltip(
                        "Preview" if is_pdf else "Download"
                    )
                    ui.button(icon="swap_horiz", on_click=lambda d=doc: replace_dialog(d)).props(
                        "flat round dense size=sm color=grey-7"
                    ).tooltip("Replace")
                    ui.button(
                        icon="delete_outline", on_click=lambda d=doc: delete_document_dialog(d)
                    ).props("flat round dense size=sm color=grey-7").tooltip("Delete")

        with (
            dialog_host,
            ui.dialog() as dialog,
            ui.card().classes("w-[32rem] max-w-full p-6 gap-3"),
        ):
            with ui.row().classes("w-full items-start justify-between no-wrap"):
                name_label = ui.label(info["name"]).classes("text-2xl font-semibold")
                with ui.row().classes("gap-1 no-wrap"):
                    ui.button(icon="edit", on_click=edit_dialog).props(
                        "flat round dense color=grey-7"
                    ).tooltip("Edit")
                    ui.button(icon="close", on_click=dialog.close).props(
                        "flat round dense color=grey-7"
                    )
            desc_label = ui.label(info["description"] or "No description").classes("text-zinc-600")
            with ui.row().classes("gap-2"):
                ui.chip(f"Created {day(info['created_at'])}", icon="event").props("outline")
                updated_chip = ui.chip(f"Updated {day(info['updated_at'])}", icon="update").props(
                    "outline"
                )
                ui.chip(f"GET /info · {status_label(info_status)}", icon="http").props("outline")
            ui.separator()
            ui.label("Documents").classes("font-semibold")
            document_list()
            uploader = (
                ui.upload(
                    multiple=True,
                    max_total_size=UPLOAD_MAX_TOTAL_SIZE,
                    on_multi_upload=upload,
                    on_rejected=rejected,
                    label="PDF or DOCX · 50 MB per project",
                )
                .props(f'accept="{UPLOAD_ACCEPT}" flat bordered')
                .classes("w-full")
            )
            ui.separator()
            ui.label("Invite a teammate").classes("font-semibold")
            ui.label("By login, they're added right away.").classes("text-xs text-zinc-500 -mt-2")
            with ui.row().classes("w-full items-center no-wrap"):
                invite_input = ui.input("Login").props("outlined dense").classes("grow")
                invite_input.on("keydown.enter", invite)
                ui.button("Invite", icon="person_add", on_click=invite).props("unelevated")
            ui.label("By email, they get a join link (owner only).").classes(
                "text-xs text-zinc-500"
            )
            with ui.row().classes("w-full items-center no-wrap"):
                email_input = ui.input("Email").props("outlined dense type=email").classes("grow")
                email_input.on("keydown.enter", share)
                ui.button("Send link", icon="forward_to_inbox", on_click=share).props("unelevated")
            ui.separator()
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                with ui.column().classes("gap-0"):
                    ui.label("Delete project").classes("font-semibold")
                    ui.label("Owner only. Removes the project and its documents.").classes(
                        "text-xs text-zinc-500"
                    )
                ui.button("Delete", icon="delete", on_click=delete_dialog).props(
                    "outline color=negative"
                )
        dialog.open()

    def project_card(project: dict[str, Any]) -> None:
        with (
            ui.card()
            .classes("cursor-pointer p-5 gap-3 hover:border-zinc-900 transition-colors")
            .on("click", lambda p=project: project_dialog(p["id"]))
        ):
            with ui.row().classes("items-center gap-3 no-wrap"):
                with ui.avatar(color="grey-3", text_color="grey-10", size="md", rounded=True):
                    ui.label(project["name"][:1].upper())
                ui.label(project["name"]).classes("text-base font-semibold truncate")
            ui.label(project["description"] or "No description").classes(
                "text-zinc-500 text-sm line-clamp-2"
            )
            ui.space()
            with ui.row().classes("w-full items-center justify-between"):
                ui.chip(f"{len(project['documents'])} documents", icon="description").props(
                    "outline dense"
                )
                ui.label(day(project["updated_at"])).classes("text-xs text-zinc-400")

    def projects_view() -> None:
        query = view["query"].lower()
        shown = [p for p in projects if query in p["name"].lower()]
        with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Projects").classes("text-2xl font-semibold tracking-tight")
                    ui.label(f"{len(projects)} in your workspace").classes("text-zinc-500")
                with ui.row().classes("items-center gap-3"):
                    search = (
                        ui.input(placeholder="Search projects", value=view["query"])
                        .props("outlined dense")
                        .classes("w-64")
                    )
                    search.on_value_change(
                        lambda e: (view.update(query=e.value or ""), content.refresh())
                    )
                    ui.button("New project", icon="add", on_click=new_project_dialog).props(
                        "unelevated"
                    )
            if shown:
                with ui.element("div").classes(
                    "w-full grid gap-4 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3"
                ):
                    for project in shown:
                        project_card(project)
            else:
                with ui.column().classes("w-full items-center py-20 gap-2 text-zinc-400"):
                    ui.icon("folder_open", size="4rem")
                    ui.label("No projects found" if projects else "No projects yet").classes(
                        "text-lg"
                    )
                    if not projects:
                        ui.button("Create your first project", on_click=new_project_dialog).props(
                            "flat"
                        )

    # -------------------------------------------------------------- system
    def system_view() -> None:
        checks: list[tuple[str, ui.label, ui.icon]] = []

        async def check(path: str, label: ui.label, icon: ui.icon) -> None:
            label.set_text("Checking...")
            try:
                status, data = await request("GET", path)
            except httpx.HTTPError as exc:
                label.set_text(f"{status_label(error_status(exc))} · {error_text(exc)}")
                icon.props("name=error color=negative")
                return
            details = ", ".join(f"{k}: {v}" for k, v in data.items())
            label.set_text(f"{status_label(status)} · {details}")
            icon.props("name=check_circle color=positive")

        async def check_all() -> None:
            for path, label, icon in checks:
                await check(path, label, icon)

        with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("System status").classes("text-2xl font-semibold tracking-tight")
                ui.button("Check all", icon="refresh", on_click=check_all).props("flat")
            for title, path in (("API", "/health"), ("Database", "/health/db")):
                with (
                    ui.card().classes("w-full p-5"),
                    ui.row().classes("w-full items-center justify-between no-wrap"),
                ):
                    with ui.row().classes("items-center gap-3 no-wrap"):
                        icon = ui.icon("help", color="grey", size="2rem")
                        with ui.column().classes("gap-0"):
                            ui.label(title).classes("font-semibold")
                            result = ui.label("Checking...").classes("text-sm text-zinc-500")
                    ui.button(
                        "Check",
                        icon="refresh",
                        on_click=lambda p=path, r=result, i=icon: check(p, r, i),
                    ).props("flat")
                checks.append((path, result, icon))
            ui.timer(0.1, check_all, once=True)

    # ------------------------------------------------------------ activity
    @ui.refreshable
    def activity_table() -> None:
        table = (
            ui.table(
                columns=[
                    {"name": "time", "label": "Time", "field": "time", "align": "left"},
                    {"name": "method", "label": "Method", "field": "method", "align": "left"},
                    {"name": "path", "label": "Path", "field": "path", "align": "left"},
                    {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    {"name": "ms", "label": "Time (ms)", "field": "ms", "align": "right"},
                ],
                rows=calls,
                row_key="id",
                pagination=20,
            )
            .props("flat")
            .classes("w-full")
        )
        table.add_slot(
            "body-cell-status",
            """
            <q-td :props="props">
                <q-badge
                    :outline="true"
                    :color="props.row.status === 0 || props.row.status >= 500 ? 'negative'
                        : props.row.status >= 400 ? 'warning' : 'positive'"
                    :label="props.row.label"
                />
            </q-td>
            """,
        )
        table.add_slot(
            "body-cell-path",
            '<q-td :props="props"><code>{{ props.row.path }}</code></q-td>',
        )

    def activity_view() -> None:
        def clear() -> None:
            calls.clear()
            activity_table.refresh()

        with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("API activity").classes("text-2xl font-semibold tracking-tight")
                    ui.label("Requests this page sent to the API, newest first").classes(
                        "text-zinc-500"
                    )
                ui.button("Clear", icon="delete_sweep", on_click=clear).props("flat")
            with ui.card().classes("w-full p-0"):
                activity_table()

    @ui.refreshable
    def content() -> None:
        if not logged_in():
            auth_view()
        elif view["page"] == "system":
            system_view()
        elif view["page"] == "activity":
            activity_view()
        else:
            projects_view()

    def mark_nav() -> None:
        for page, button in nav_buttons.items():
            button.classes(
                add="bg-zinc-200/70" if page == view["page"] else "",
                remove="" if page == view["page"] else "bg-zinc-200/70",
            )

    def navigate(page: str) -> None:
        view["page"] = page
        mark_nav()
        content.refresh()

    # --------------------------------------------------------------- shell
    with ui.header().classes("items-center justify-between bg-white text-zinc-900 px-4") as header:
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="menu", on_click=lambda: drawer.toggle()).props("flat round dense")
            brand()
        with ui.row().classes("items-center gap-4"):
            with ui.row().classes(
                "items-center gap-2 no-wrap px-3 py-1 rounded-full border border-zinc-200"
            ):
                health_dot = ui.element("span").classes("w-2 h-2 rounded-full bg-zinc-300")
                health_text = ui.label("API").classes("text-xs text-zinc-600")
            with ui.button().props("flat round dense"):
                with ui.avatar(color="primary", text_color="white", size="sm"):
                    avatar_label = ui.label("")
                with ui.menu():
                    user_label = ui.label("").classes("px-4 py-2 text-sm text-zinc-500")
                    ui.separator()
                    ui.menu_item("Sign out", on_click=logout)

    nav_buttons: dict[str, ui.button] = {}
    with (
        ui.left_drawer(value=True).classes("pt-6 px-3 gap-1").props("width=220 bordered") as drawer
    ):
        for page, title, icon in (
            ("projects", "Projects", "folder"),
            ("system", "System status", "monitor_heart"),
            ("activity", "API activity", "swap_vert"),
        ):
            nav_buttons[page] = (
                ui.button(title, icon=icon, on_click=lambda p=page: navigate(p))
                .props("flat align=left no-caps color=grey-9")
                .classes("w-full")
            )

    content()
    dialog_host = ui.element("div")

    async def health_monitor() -> None:
        try:
            await request("GET", "/health", log=False)
            health_dot.classes(replace="w-2 h-2 rounded-full bg-green-600")
            health_text.set_text("API online")
        except httpx.HTTPError:
            health_dot.classes(replace="w-2 h-2 rounded-full bg-red-600")
            health_text.set_text("API offline")

    ui.timer(30.0, health_monitor)
    ui.timer(0.1, health_monitor, once=True)

    async def join_pending() -> None:
        token = app.storage.user.pop(JOIN_TOKEN_KEY, None)
        if not token or not logged_in():
            return
        try:
            status, project = await request("POST", "/join", json_body={"token": token}, auth=True)
        except httpx.HTTPError as exc:
            if error_status(exc) == 404:
                ui.notify(
                    "Invitation invalid or expired", type="negative", caption=status_label(404)
                )
            else:
                notify_error(exc)
            return
        notify_ok(f"Joined {project['name']}", status)
        await reload_view()
        await project_dialog(project["id"])

    async def restore_session() -> None:
        if logged_in():
            await load_projects()
            content.refresh()
            await join_pending()

    apply_state()
    ui.timer(0.1, restore_session, once=True)


@ui.page("/join")
def join(token: str = "") -> RedirectResponse:
    if token:
        app.storage.user[JOIN_TOKEN_KEY] = token
    return RedirectResponse("/")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(storage_secret=STORAGE_SECRET, port=8080, title="Projects", favicon="▪️")
