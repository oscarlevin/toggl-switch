#!/usr/bin/env python3
"""toggl-switch: one-tap task switching for Toggl Track.

Running `toggl-switch <preset>` stops whatever timer is running and starts
the timer described by <preset> in your config file. Bind that command to
buttons, hotkeys or home-screen widgets on each device.

Standard library only (Python 3.11+), so it runs anywhere Python does,
including Termux on Android.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = os.environ.get("TOGGL_API_BASE", "https://api.track.toggl.com/api/v9")
CREATED_WITH = "toggl-switch"
RESERVED = {"stop", "status", "list", "shortcuts"}


class TogglError(Exception):
    pass


# ---------------------------------------------------------------- config


def config_path() -> Path:
    if env := os.environ.get("TOGGL_SWITCH_CONFIG"):
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "toggl-switch" / "config.toml"


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        raise TogglError(
            f"No config file at {path}. Copy config.example.toml there and edit it."
        )
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    cfg["api_token"] = os.environ.get("TOGGL_API_TOKEN") or cfg.get("api_token")
    if not cfg["api_token"]:
        raise TogglError("No API token: set api_token in the config or TOGGL_API_TOKEN.")
    cfg.setdefault("presets", {})
    bad = RESERVED & set(cfg["presets"])
    if bad:
        raise TogglError(f"Preset names clash with commands: {', '.join(sorted(bad))}")
    return cfg


# ---------------------------------------------------------------- API


class Toggl:
    def __init__(self, token: str, workspace_id: int | None = None):
        auth = base64.b64encode(f"{token}:api_token".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }
        self._workspace_id = workspace_id
        self._projects: list[dict] | None = None

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            API_BASE + path, data=data, method=method, headers=self.headers
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace").strip()
            if e.code == 403:
                detail = "check your API token"
            raise TogglError(f"Toggl API {method} {path} -> {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise TogglError(f"Could not reach Toggl: {e.reason}") from None
        return json.loads(raw) if raw.strip() else None

    @property
    def workspace_id(self) -> int:
        if self._workspace_id is None:
            self._workspace_id = self.request("GET", "/me")["default_workspace_id"]
        return self._workspace_id

    def current(self) -> dict | None:
        return self.request("GET", "/me/time_entries/current")

    def stop(self, entry: dict) -> dict:
        wid = entry.get("workspace_id") or self.workspace_id
        return self.request("PATCH", f"/workspaces/{wid}/time_entries/{entry['id']}/stop")

    def project_id(self, project) -> int | None:
        if project is None or project == "":
            return None
        if isinstance(project, int) or str(project).isdigit():
            return int(project)
        if self._projects is None:
            query = urllib.parse.urlencode({"active": "true", "per_page": 200})
            self._projects = self.request(
                "GET", f"/workspaces/{self.workspace_id}/projects?{query}"
            ) or []
        for p in self._projects:
            if p["name"].casefold() == str(project).casefold():
                return p["id"]
        raise TogglError(f"No active project named {project!r} in workspace {self.workspace_id}")

    def start(self, preset: dict) -> dict:
        body = {
            "created_with": CREATED_WITH,
            "workspace_id": self.workspace_id,
            "description": preset.get("description", ""),
            "start": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": -1,  # negative duration = running timer
            "billable": bool(preset.get("billable", False)),
        }
        if (pid := self.project_id(preset.get("project"))) is not None:
            body["project_id"] = pid
        if tags := preset.get("tags"):
            body["tags"] = list(tags)
        return self.request("POST", f"/workspaces/{self.workspace_id}/time_entries", body)


def matches(entry: dict, preset: dict, project_id: int | None) -> bool:
    return (
        entry.get("description", "") == preset.get("description", "")
        and entry.get("project_id") == project_id
        and sorted(entry.get("tags") or []) == sorted(preset.get("tags") or [])
    )


# ---------------------------------------------------------------- feedback


def notify(cfg: dict, title: str, message: str) -> None:
    print(f"{title}: {message}")
    if not cfg.get("notify", True):
        return
    try:
        if shutil.which("termux-toast"):
            subprocess.Popen(["termux-toast", f"{title}: {message}"])
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "toggl-switch", "-t", "3000", title, message])
        elif sys.platform == "win32":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                f"$n.ShowBalloonTip(3000,'{_ps(title)}','{_ps(message)}','Info');"
                "Start-Sleep 4;$n.Dispose()"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except OSError:
        pass


def _ps(s: str) -> str:
    return s.replace("'", "''")


def describe(entry: dict) -> str:
    return entry.get("description") or "(no description)"


def elapsed(entry: dict) -> str:
    start = datetime.fromisoformat(entry["start"].replace("Z", "+00:00"))
    mins = int((datetime.now(timezone.utc) - start).total_seconds() // 60)
    return f"{mins // 60}h {mins % 60:02d}m"


# ---------------------------------------------------------------- shortcuts


def make_shortcuts(cfg: dict) -> None:
    script = Path(__file__).resolve()
    names = ["stop", *cfg["presets"]]
    if sys.platform == "win32":
        desktop = Path(os.environ["USERPROFILE"]) / "Desktop" / "Toggl"
        desktop.mkdir(parents=True, exist_ok=True)
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = pythonw if pythonw.exists() else Path(sys.executable)
        for name in names:
            lnk = desktop / f"Toggl - {label(cfg, name)}.lnk"
            ps = (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
                "$s.TargetPath='{exe}';$s.Arguments='\"{script}\" {name}';$s.Save()"
            ).format(lnk=_ps(str(lnk)), exe=_ps(str(exe)), script=_ps(str(script)), name=name)
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
        print(f"Shortcuts written to {desktop}")
    elif "TERMUX_VERSION" in os.environ:
        folder = Path.home() / ".shortcuts"
        folder.mkdir(exist_ok=True)
        for name in names:
            f = folder / f"Toggl {label(cfg, name)}"
            f.write_text(f"#!/data/data/com.termux/files/usr/bin/sh\npython {script} {name}\n")
            f.chmod(0o755)
        print(f"Termux:Widget scripts written to {folder}")
    else:
        folder = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / f"toggl-switch-{name}.desktop").write_text(
                "[Desktop Entry]\nType=Application\n"
                f"Name=Toggl: {label(cfg, name)}\n"
                f"Exec={sys.executable} {script} {name}\n"
                "Icon=chronometer\nTerminal=false\nCategories=Utility;\n"
            )
        print(f".desktop launchers written to {folder}")


def label(cfg: dict, name: str) -> str:
    if name == "stop":
        return "Stop"
    return cfg["presets"][name].get("label") or name


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="toggl-switch",
        description="Stop the running Toggl timer and start a preset one.",
    )
    parser.add_argument("command", help="a preset name, or: stop, status, list, shortcuts")
    args = parser.parse_args(argv)
    cfg = {"notify": True}
    try:
        cfg = load_config()
        if args.command == "list":
            for name, p in cfg["presets"].items():
                extra = f"  [{p['project']}]" if p.get("project") else ""
                print(f"{name:15} {p.get('description', '')}{extra}")
            return 0
        if args.command == "shortcuts":
            make_shortcuts(cfg)
            return 0

        api = Toggl(cfg["api_token"], cfg.get("workspace_id"))
        running = api.current()

        if args.command == "status":
            print(f"{describe(running)} ({elapsed(running)})" if running else "No timer running")
            return 0
        if args.command == "stop":
            if running:
                api.stop(running)
                notify(cfg, "Stopped", f"{describe(running)} ({elapsed(running)})")
            else:
                notify(cfg, "Toggl", "No timer running")
            return 0

        preset = cfg["presets"].get(args.command)
        if preset is None:
            raise TogglError(
                f"Unknown preset {args.command!r}. Known: {', '.join(cfg['presets']) or 'none'}"
            )
        if running and matches(running, preset, api.project_id(preset.get("project"))):
            notify(cfg, "Already tracking", describe(running))
            return 0
        if running:
            api.stop(running)
        entry = api.start(preset)
        notify(cfg, "Tracking", describe(entry))
        return 0
    except TogglError as e:
        notify(cfg, "toggl-switch error", str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
