from __future__ import annotations

import itertools
import os
import time
from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from nicegui import app, events, ui

API_BASE = os.environ.get("API_URL", "http://localhost:8000")
STORAGE_SECRET = os.environ.get("UI_STORAGE_SECRET", "local-dev-only")

# Contract from backlog E4-03; the endpoint is not in the API yet.
UPLOAD_PATH = "/project/{project_id}/documents"
UPLOAD_FIELD = "files"
UPLOAD_ACCEPT = ".pdf,.docx"
UPLOAD_MAX_FILES = 10
UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024

GRADIENT = "linear-gradient(135deg, #4f46e5 0%, #7c3aed 55%, #db2777 100%)"


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


def size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{max(size // 1024, 1)} KB"


@ui.page("/")
def index() -> None:
    ui.colors(primary="#4f46e5")
    ui.query(".nicegui-content").classes("p-0 gap-0")
    ui.query("body").classes("bg-slate-50")

    view = {"page": "projects", "query": ""}
    projects: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    call_ids = itertools.count(1)

    def logged_in() -> bool:
        return bool(app.storage.user.get("token"))

    def apply_state() -> None:
        header.set_visibility(logged_in())
        drawer.set_visibility(logged_in())
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

        with (
            ui.column()
            .classes("w-full items-center justify-center gap-6 p-4")
            .style(f"min-height:100vh; background:{GRADIENT};")
        ):
            with ui.row().classes("items-center gap-3 text-white"):
                ui.icon("rocket_launch", size="2.5rem")
                ui.label("Projects").classes("text-4xl font-bold")
            ui.label("Manage your projects and collaborate with your team.").classes(
                "text-white/80 -mt-4"
            )
            with ui.card().classes("w-full max-w-md p-6 rounded-2xl shadow-2xl"):
                with ui.tabs().classes("w-full") as tabs:
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
                            .props("size=lg unelevated")
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
                            .props("size=lg unelevated")
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

        with dialog_host, ui.dialog() as dialog, ui.card().classes("w-96 p-6 gap-3 rounded-2xl"):
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
                if error_status(exc) in (404, 405) and error_text(exc) in (
                    "Not Found",
                    "Method Not Allowed",
                ):
                    ui.notify(
                        "The upload endpoint is not available in the API yet",
                        type="warning",
                        caption=status_label(error_status(exc)),
                    )
                else:
                    notify_error(exc)
                uploader.reset()
                return
            uploader.reset()
            notify_ok(f"Uploaded {len(docs)} file(s)", status)
            await load_projects()
            document_list.refresh()
            content.refresh()

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

            with dialog_host, ui.dialog() as edit, ui.card().classes("w-96 p-6 gap-3 rounded-2xl"):
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

        def rejected() -> None:
            ui.notify(
                f"Only PDF or DOCX, up to {UPLOAD_MAX_FILES} files of "
                f"{size_text(UPLOAD_MAX_FILE_SIZE)} each",
                type="warning",
            )

        @ui.refreshable
        def document_list() -> None:
            documents = next((p["documents"] for p in projects if p["id"] == project_id), [])
            if not documents:
                ui.label("No documents yet").classes("text-slate-400 text-sm")
            for doc in documents:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("description", color="primary")
                    ui.label(doc["filename"])
                    ui.label(size_text(doc["size_bytes"])).classes("text-xs text-slate-400")

        with (
            dialog_host,
            ui.dialog() as dialog,
            ui.card().classes("w-[32rem] max-w-full p-6 gap-3 rounded-2xl"),
        ):
            with ui.row().classes("w-full items-start justify-between no-wrap"):
                name_label = ui.label(info["name"]).classes("text-2xl font-semibold")
                with ui.row().classes("gap-1 no-wrap"):
                    ui.button(icon="edit", on_click=edit_dialog).props("flat round dense").tooltip(
                        "Edit"
                    )
                    ui.button(icon="close", on_click=dialog.close).props("flat round dense")
            desc_label = ui.label(info["description"] or "No description").classes("text-slate-600")
            with ui.row().classes("gap-2"):
                ui.chip(f"Created {day(info['created_at'])}", icon="event").props("outline")
                updated_chip = ui.chip(f"Updated {day(info['updated_at'])}", icon="update").props(
                    "outline"
                )
                ui.chip(f"GET /info · {status_label(info_status)}", icon="http").props(
                    "outline color=positive"
                )
            ui.separator()
            ui.label("Documents").classes("font-semibold")
            document_list()
            uploader = (
                ui.upload(
                    multiple=True,
                    max_files=UPLOAD_MAX_FILES,
                    max_file_size=UPLOAD_MAX_FILE_SIZE,
                    on_multi_upload=upload,
                    on_rejected=rejected,
                    label="PDF or DOCX, up to 10 MB each",
                )
                .props(f'accept="{UPLOAD_ACCEPT}" flat bordered')
                .classes("w-full")
            )
            ui.separator()
            ui.label("Invite a teammate").classes("font-semibold")
            with ui.row().classes("w-full items-center no-wrap"):
                invite_input = ui.input("Login").props("outlined dense").classes("grow")
                invite_input.on("keydown.enter", invite)
                ui.button("Invite", icon="person_add", on_click=invite).props("unelevated")
        dialog.open()

    def project_card(project: dict[str, Any]) -> None:
        with (
            ui.card()
            .classes("cursor-pointer p-5 gap-2 rounded-2xl hover:shadow-xl transition-shadow")
            .on("click", lambda p=project: project_dialog(p["id"]))
        ):
            with ui.row().classes("items-center gap-3 no-wrap"):
                with ui.avatar(color="primary", text_color="white", size="md", rounded=True):
                    ui.label(project["name"][:1].upper())
                ui.label(project["name"]).classes("text-lg font-semibold truncate")
            ui.label(project["description"] or "No description").classes(
                "text-slate-500 text-sm line-clamp-2"
            )
            ui.space()
            with ui.row().classes("w-full items-center justify-between"):
                ui.chip(f"{len(project['documents'])} documents", icon="description").props(
                    "outline dense"
                )
                ui.label(day(project["updated_at"])).classes("text-xs text-slate-400")

    def projects_view() -> None:
        query = view["query"].lower()
        shown = [p for p in projects if query in p["name"].lower()]
        with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-6"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Projects").classes("text-3xl font-bold")
                    ui.label(f"{len(projects)} in your workspace").classes("text-slate-500")
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
                with ui.column().classes("w-full items-center py-20 gap-2 text-slate-400"):
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
                ui.label("System status").classes("text-3xl font-bold")
                ui.button("Check all", icon="refresh", on_click=check_all).props("flat")
            for title, path in (("API", "/health"), ("Database", "/health/db")):
                with (
                    ui.card().classes("w-full p-5 rounded-2xl"),
                    ui.row().classes("w-full items-center justify-between no-wrap"),
                ):
                    with ui.row().classes("items-center gap-3 no-wrap"):
                        icon = ui.icon("help", color="grey", size="2rem")
                        with ui.column().classes("gap-0"):
                            ui.label(title).classes("font-semibold")
                            result = ui.label("Checking...").classes("text-sm text-slate-500")
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
        table = ui.table(
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
        ).classes("w-full")
        table.add_slot(
            "body-cell-status",
            """
            <q-td :props="props">
                <q-badge
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
                    ui.label("API activity").classes("text-3xl font-bold")
                    ui.label("Requests this page sent to the API, newest first").classes(
                        "text-slate-500"
                    )
                ui.button("Clear", icon="delete_sweep", on_click=clear).props("flat")
            with ui.card().classes("w-full p-0 rounded-2xl"):
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

    def navigate(page: str) -> None:
        view["page"] = page
        content.refresh()

    # --------------------------------------------------------------- shell
    with ui.header().classes(
        "items-center justify-between bg-white text-slate-800 shadow-sm"
    ) as header:
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="menu", on_click=lambda: drawer.toggle()).props("flat round dense")
            ui.icon("rocket_launch", color="primary", size="1.8rem")
            ui.label("Projects").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-4"):
            health_chip = ui.chip("API", icon="circle", color="grey").props("outline dense")
            with ui.button().props("flat round dense"):
                with ui.avatar(color="primary", text_color="white", size="md"):
                    avatar_label = ui.label("")
                with ui.menu():
                    user_label = ui.label("").classes("px-4 py-2 text-sm text-slate-500")
                    ui.separator()
                    ui.menu_item("Sign out", on_click=logout)

    with ui.left_drawer(value=True).classes("bg-white pt-6").props("width=220 bordered") as drawer:
        for page, title, icon in (
            ("projects", "Projects", "folder"),
            ("system", "System status", "monitor_heart"),
            ("activity", "API activity", "swap_vert"),
        ):
            ui.button(title, icon=icon, on_click=lambda p=page: navigate(p)).props(
                "flat align=left no-caps"
            ).classes("w-full")

    content()
    dialog_host = ui.element("div")

    async def health_monitor() -> None:
        try:
            await request("GET", "/health", log=False)
            health_chip.props("color=positive")
            health_chip.set_text("API online")
        except httpx.HTTPError:
            health_chip.props("color=negative")
            health_chip.set_text("API offline")

    ui.timer(30.0, health_monitor)
    ui.timer(0.1, health_monitor, once=True)

    async def restore_session() -> None:
        if logged_in():
            await load_projects()
            content.refresh()

    apply_state()
    ui.timer(0.1, restore_session, once=True)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(storage_secret=STORAGE_SECRET, port=8080, title="Projects", favicon="🚀")
