# Admin Guide

## Default credentials

| | |
| --- | --- |
| URL | `http://tremplin.local/settings` |
| Username | `score` |
| Password | `swimming` |

Change these in **Settings → Account** before deploying at a meet.

---

## Pages

| URL | Description |
| --- | --- |
| `/` | Redirects to `/scoreboard` |
| `/scoreboard` | Full scoreboard (lane count from Meet Setup settings) |
| `/live` | Compact live view |
| `/mobile` | Mobile shell — three-tab view (Scoreboard, Results, Schedule) |
| `/results` | Results after each heat |
| `/schedule` | Meet schedule with start times and heat entry lists |
| `/settings` | Admin settings (login required) |
| `/info` | Hardware wiring and connection guide |
| `/help` | Help and settings reference |

Append `?test` to any scoreboard URL to show mode control buttons (Splash, Intro, Running, Results, Next Heat) overlaid on the display — useful for testing without a live console.

---

## Meet-day workflow

1. In Splash Meet Manager: **File → Export → Lenex** → save as `.lxf`
2. Copy the `.lxf` file to Pi #1 at `~/TremplinData/meet/`  
   (or upload it via **Settings → Meet Setup → Choose file**)
3. Click **Reload Names** — swimmer names and clubs are now live on the scoreboard

---

## Settings tabs

| Tab | Description |
| --- | --- |
| **Meet Setup** | Meet title, Lenex/Hytek file upload, reload names, sponsor image, language, label style, lane count |
| **Timing** | Serial port, console type, connection status, serial monitor (raw hex packets) |
| **Clock** | Sync with NTP; set date and time manually when offline; install/remove Adafruit PiRTC (DS3231) hardware clock |
| **Flow** | Intro, results, and server-update timeouts; finish debounce |
| **Display** | Show/hide column headers and columns (Name, Club, Delta, Position); podium highlighting |
| **Theme** | Built-in colour schemes; override individual colours and fonts; save as a custom theme |
| **Network** | WiFi management; view connected scoreboard clients |
| **Update & Backup** | Pull latest version from GitHub, sync dependencies, restart; download or restore a backup of `~/Scoreboard` |
| **Test** | Play back pre-recorded sessions; adjust playback speed; record live serial sessions |
| **Terminal** | In-browser terminal — Shell, raspi-config, Scoreboard logs, dmesg, serial ports |
| **Cloud** | Cloud relay URL, relay key, location and sport for the meet picker |
| **Account** | Change the admin UI username and password |

---

## Data folders on Pi #1

| Path | Contents |
| --- | --- |
| `~/TremplinData/meet/` | Lenex `.lxf` and Hytek `.csv` files — copy here on meet day |
| `~/TremplinData/images/` | Sponsor or club logo images for the splash screen |
| `~/TremplinData/recorded/` | Custom recorded sessions for playback in the Test tab |
| `~/TremplinData/locale/` | Custom locale `.toml` overrides (takes priority over built-in locales) |
| `~/TremplinData/themes/` | Custom theme `.toml` files |
| `~/TremplinData/console_decoders/` | Local-only decoder plugins (`.py` files) — loaded at startup, not tracked by git |
| `~/TremplinData/settings.json` | All admin UI settings |

---

## Localisation

Built-in languages:

| File | Language |
| --- | --- |
| `locales/en.toml` | English |
| `locales/fr.toml` | Français |
| `locales/es.toml` | Español |

Each file defines short and long label variants:

```toml
[meta]
name = "English"

[labels]
event = { short = "EV",   long = "EVENT" }
heat  = { short = "HT",   long = "HEAT"  }
lane  = { short = "LN",   long = "LANE"  }
place = { short = "PL",   long = "PLACE" }
time  = { short = "TIME", long = "TIME"  }
name  = { short = "NAME", long = "NAME"  }
```

Add any `.toml` with the same structure to `locales/` (or upload via the Display tab) and it appears in the Language dropdown automatically. Files placed in `~/TremplinData/locale/` take priority over the built-in ones.

---

## Service management (SSH into Pi #1)

The app runs as a systemd service named **`tremplin`**. Most of this is also available from the admin UI — the **Power** tab does restart / reboot / shutdown, and **Terminal** has a "Scoreboard logs" launcher and a "Save Logs" button — but from an SSH session:

```sh
sudo systemctl restart tremplin    # restart after manual changes (same as the Power tab)
sudo systemctl stop tremplin       # stop the service
sudo systemctl start tremplin      # start it again
systemctl status tremplin          # current state
journalctl -u tremplin -f          # follow live logs
```

---

## CLI troubleshooting

Most issues are handled in the UI — serial port + Serial Monitor in **Timing**, WiFi and clock tabs, meet-file upload in **Meet Setup**. For the rest:

**The service won't start.** Run `journalctl -u tremplin -f` to see the error. Common causes: wrong serial port, missing Python dependencies (run `uv sync` in the repo directory), or another process already bound to port 5000.

**Serial adapter not detected.** Run `ls /dev/ttyUSB*` on Pi #1 to list adapters. The service user must be in the `dialout` group — check with `groups`; if missing, `sudo usermod -aG dialout <user>` and reboot. (The installer normally handles this.)

**`tremplin.local` unreachable.** See [troubleshooting-tremplin-local-unreachable.md](troubleshooting-tremplin-local-unreachable.md).
