# toggl-switch

One-tap task switching for [Toggl Track](https://toggl.com/track/).

You define a few common tasks ("presets") once. Each one becomes a button,
hotkey or home-screen widget. Tapping it **stops whatever timer is running and
starts that task**. If that task is already running, nothing happens.

```
toggl-switch grading     # switch to the "grading" preset
toggl-switch stop        # stop the running timer
toggl-switch status      # show what's running
toggl-switch list        # list presets
toggl-switch shortcuts   # generate launchers/buttons for this device
```

It is a single Python file (`toggl_switch.py`), standard library only,
Python 3.11+. It works on Linux, Windows and Android (via Termux).

## Setup

1. Get your API token from <https://track.toggl.com/profile> (bottom of the page).
2. Copy `config.example.toml` to:
   - Linux / Termux: `~/.config/toggl-switch/config.toml`
   - Windows: `%APPDATA%\toggl-switch\config.toml`
3. Paste in your token and edit the presets. Projects can be given by name
   (case-insensitive) or numeric id.
4. Try it: `python3 toggl_switch.py list`, then `python3 toggl_switch.py <preset>`.

The config holds your API token, so keep it out of git (the repo's
`.gitignore` already excludes `config.toml`).

## Making buttons

### Linux

`python3 toggl_switch.py shortcuts` writes one `.desktop` launcher per preset
(plus "Stop") to `~/.local/share/applications`. They show up in your app
launcher as "Toggl: Grading" and so on. You can pin them to a panel/dock or
search for them.

For hotkeys, bind keyboard shortcuts in your desktop settings to commands like
`python3 /path/to/toggl_switch.py grading`. In GNOME that's
Settings → Keyboard → Custom Shortcuts. In KDE it's System Settings → Shortcuts.

You get a `notify-send` notification after each switch.

### Windows

`python toggl_switch.py shortcuts` creates a `Toggl` folder on your Desktop with
one shortcut per preset. They run via `pythonw`, so no console window flashes.
You can drag them to the taskbar or Start menu. Give a shortcut a hotkey under
Properties → Shortcut key.

A balloon notification confirms each switch.

### Android, option A: Termux (same script)

1. Install **Termux** and **Termux:Widget** from F-Droid. Install
   **Termux:API** too if you want toasts.
2. In Termux: `pkg install python git termux-api`, clone this repo, and put
   your config at `~/.config/toggl-switch/config.toml`.
3. `python toggl_switch.py shortcuts` writes scripts to `~/.shortcuts`.
4. Add a Termux:Widget widget to your home screen. It lists every preset as a
   tappable button. You can also add a single-task 1×1 shortcut.

### Android, option B: HTTP Shortcuts (no Termux)

The [HTTP Shortcuts](https://http-shortcuts.rmy.ch/) app can run a small
script per home-screen button. `android/http-shortcuts.js` is a port of the
same logic, and setup steps are in the comments at the top of that file. This
option needs numeric project ids. You'll find a project's id in its URL in the
Toggl web app.

## How it works

Each switch makes these calls to the Toggl API v9:

1. `GET /me/time_entries/current` finds the running entry, if any.
2. If that entry already matches the preset (description, project, tags), it
   stops there.
3. Otherwise `PATCH .../time_entries/{id}/stop` stops it.
4. `POST /workspaces/{wid}/time_entries` with `duration: -1` starts a new
   running entry.

Entries are tagged `created_with: toggl-switch`.

## Tests

```
python3 -m unittest discover tests
```

The tests run the real script against a local fake Toggl server, so they need
no network or account.
