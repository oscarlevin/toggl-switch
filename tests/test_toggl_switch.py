"""End-to-end tests against a fake Toggl API server (no network needed).

Run with:  python -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class FakeToggl:
    def __init__(self):
        self.entries = []
        self.calls = []
        self.next_id = 100

    @property
    def running(self):
        return next((e for e in self.entries if e["duration"] < 0), None)


def make_handler(state: FakeToggl):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self, method):
            path = self.path.replace("/api/v9", "", 1)
            state.calls.append((method, path))
            if not self.headers.get("Authorization", "").startswith("Basic "):
                return self._send({}, 403)
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            if method == "GET" and path == "/me":
                return self._send({"default_workspace_id": 1})
            if method == "GET" and path == "/me/time_entries/current":
                return self._send(state.running)
            if method == "GET" and path.startswith("/workspaces/1/projects"):
                return self._send([{"id": 7, "name": "MATH 228"}])
            if method == "PATCH" and path.endswith("/stop"):
                eid = int(path.split("/")[-2])
                entry = next(e for e in state.entries if e["id"] == eid)
                entry["duration"] = 60
                return self._send(entry)
            if method == "POST" and path == "/workspaces/1/time_entries":
                entry = dict(body, id=state.next_id)
                state.next_id += 1
                state.entries.append(entry)
                return self._send(entry)
            return self._send({"error": "not found"}, 404)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_PATCH(self):
            self._route("PATCH")

    return Handler


CONFIG = """
api_token = "abc"
notify = false

[presets.grading]
description = "Grading"
project = "math 228"
tags = ["teaching"]

[presets.email]
description = "Email"
"""


class TogglSwitchTest(unittest.TestCase):
    def setUp(self):
        self.state = FakeToggl()
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.state))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Path(self.tmp.name) / "config.toml"
        cfg.write_text(CONFIG)
        os.environ["TOGGL_SWITCH_CONFIG"] = str(cfg)
        os.environ["TOGGL_API_BASE"] = f"http://127.0.0.1:{self.server.server_port}/api/v9"
        os.environ.pop("TOGGL_API_TOKEN", None)
        os.environ["NO_PROXY"] = "127.0.0.1"
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import importlib
        import toggl_switch

        self.ts = importlib.reload(toggl_switch)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_start_from_idle(self):
        self.assertEqual(self.ts.main(["grading"]), 0)
        e = self.state.running
        self.assertEqual(e["description"], "Grading")
        self.assertEqual(e["project_id"], 7)  # resolved case-insensitively
        self.assertEqual(e["tags"], ["teaching"])
        self.assertEqual(e["created_with"], "toggl-switch")

    def test_switch_stops_previous(self):
        self.ts.main(["grading"])
        self.ts.main(["email"])
        self.assertEqual(len(self.state.entries), 2)
        self.assertEqual(self.state.entries[0]["duration"], 60)  # stopped
        self.assertEqual(self.state.running["description"], "Email")
        self.assertNotIn("project_id", self.state.running)

    def test_same_preset_is_noop(self):
        self.ts.main(["grading"])
        self.ts.main(["grading"])
        self.assertEqual(len(self.state.entries), 1)
        self.assertIsNotNone(self.state.running)

    def test_project_list_fetched_once(self):
        self.ts.main(["grading"])
        self.state.calls.clear()
        self.ts.main(["grading"])
        gets = [c for c in self.state.calls if "/projects" in c[1]]
        self.assertEqual(len(gets), 1)

    def test_stop(self):
        self.ts.main(["grading"])
        self.assertEqual(self.ts.main(["stop"]), 0)
        self.assertIsNone(self.state.running)
        self.assertEqual(self.ts.main(["stop"]), 0)  # nothing running is fine

    def test_unknown_preset(self):
        self.assertEqual(self.ts.main(["nope"]), 1)
        self.assertEqual(self.state.entries, [])


if __name__ == "__main__":
    unittest.main()
