// toggl-switch for the "HTTP Shortcuts" Android app (no Termux needed).
//
// Setup (once per button):
//   1. In HTTP Shortcuts, create a new shortcut of type "Scripting Shortcut".
//   2. Paste this whole file into its script.
//   3. Edit the PRESET block below for that button.
//   4. Put your API token in a Global Variable named "toggl_token"
//      (Variables > + > Constant) so it isn't copied into every shortcut.
//   5. Long-press the shortcut > "Place on Home Screen", or add the
//      app's widget for a grid of buttons.
//
// Set the description to "" and leave the rest out to make a Stop button:
//   const PRESET = { stop: true };

const PRESET = {
  description: "Grading",
  project_id: null,        // numeric id from the project's URL in Toggl, or null
  tags: ["teaching"],
  billable: false,
};

const API = "https://api.track.toggl.com/api/v9";
const auth = "Basic " + base64encode(getVariable("toggl_token") + ":api_token");
const headers = { "Authorization": auth, "Content-Type": "application/json" };

function call(method, path, body) {
  const res = sendHttpRequest(API + path, {
    method: method,
    headers: headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status >= 300) {
    showToast("Toggl error " + res.status + ": " + res.body);
    abort();
  }
  return res.body && res.body.trim() !== "null" ? JSON.parse(res.body) : null;
}

const running = call("GET", "/me/time_entries/current");

if (PRESET.stop) {
  if (running) call("PATCH", `/workspaces/${running.workspace_id}/time_entries/${running.id}/stop`);
  showToast(running ? "Stopped: " + (running.description || "timer") : "No timer running");
  abort();
}

const sameTags = JSON.stringify([...(running?.tags || [])].sort()) ===
                 JSON.stringify([...(PRESET.tags || [])].sort());
if (running && running.description === PRESET.description &&
    (running.project_id || null) === (PRESET.project_id || null) && sameTags) {
  showToast("Already tracking: " + PRESET.description);
  abort();
}

if (running) call("PATCH", `/workspaces/${running.workspace_id}/time_entries/${running.id}/stop`);

const wid = running ? running.workspace_id : call("GET", "/me").default_workspace_id;
const entry = {
  created_with: "toggl-switch",
  workspace_id: wid,
  description: PRESET.description,
  start: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
  duration: -1,
  billable: !!PRESET.billable,
};
if (PRESET.project_id) entry.project_id = PRESET.project_id;
if (PRESET.tags && PRESET.tags.length) entry.tags = PRESET.tags;

call("POST", `/workspaces/${wid}/time_entries`, entry);
showToast("Tracking: " + PRESET.description);
