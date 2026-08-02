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
| `/operator` | Operator control view |
| `/mobile` | Mobile shell — three-tab view (Scoreboard, Results, Schedule) |
| `/results` | Results after each heat |
| `/schedule` | Meet schedule with start times and heat entry lists |
| `/console` | Live serial console viewer |
| `/settings` | Admin settings (login required) |

Append `?test` to any scoreboard URL to show mode control buttons (Splash, Intro, Running, Results, Next Heat) overlaid on the display — useful for testing without a live console.

---

## Meet-day workflow

1. In Splash Meet Manager: **File → Export → Lenex** → save as a `.lxf` file.
2. In **Settings → Meet Setup**, click **Add Meet File** and upload the `.lxf` — swimmer and
   club names go live on the scoreboard immediately. *(Alternatively, upload a Hytek `.csv`
   event schedule so event names appear in the header.)*
3. Open the scoreboard on the TV at `http://tremplin.local/`.
4. Start the CTS console — times appear automatically as heats run.

> Prefer the command line? See [Manual and CLI reference](#manual-and-cli-reference) for
> placing meet files directly in `~/TremplinData/meet/`.

---

## Settings tabs

| Tab | Description |
| --- | --- |
| **Meet Setup** | Upload Lenex `.lxf` / Hytek `.csv` meet files; pool length, touchpads, lane count |
| **Timing** | Serial port, console type, connection status, serial monitor (raw hex packets) |
| **Clock** | Sync with NTP; set date and time manually when offline; install/remove Adafruit PiRTC (DS3231) hardware clock |
| **Flow** | Intro, results, and server-update timeouts; finish debounce |
| **Display** | Show/hide column headers and columns (Name, Club, Delta, Position); podium highlighting |
| **Theme** | Built-in colour schemes; override individual colours and fonts; save as a custom theme |
| **Network** | WiFi management; view connected scoreboard clients |
| **Update & Backup** | Pull latest version from GitHub, sync dependencies, restart; download or restore a backup of `~/TremplinData` |
| **Test** | Play back pre-recorded sessions; adjust playback speed; record live serial sessions |
| **Terminal** | In-browser terminal — Shell, raspi-config, Scoreboard logs, dmesg, serial ports |
| **Cloud** | Cloud relay URL and key; per-meet picker appearance (title, image, home icon, location, sport) |
| **Power** | Restart the app service, reboot, or shut down the Pi — press-and-hold to confirm |
| **Account** | Change the admin UI username and password (via the sidebar account menu) |

> In the sidebar, **Flow / Display / Theme** live under the **Scoreboard** group; **Cloud**
> and **Network** are top-level.

---

## Data folders on Pi #1

| Path | Contents |
| --- | --- |
| `~/TremplinData/meet/` | Lenex `.lxf` and Hytek `.csv` meet files (uploaded via Meet Setup, or [placed here manually](#manual-and-cli-reference)) |
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

## Manual and CLI reference

Everything here can also be done from the admin UI — these are the manual equivalents and
lower-level tools for when you're SSH'd into Pi #1.

### Load meet files manually

Instead of uploading in **Meet Setup**, copy `.lxf` / `.csv` files to `~/TremplinData/meet/`.
They appear in the Meet Setup file dropdown — select one to load it live.

### Service management

The app runs as a systemd service named **`tremplin`**. The **Power** tab does restart /
reboot / shutdown and **Terminal** has a "Scoreboard logs" launcher and "Save Logs", but
over SSH:

```sh
sudo systemctl restart tremplin    # restart after manual changes (same as the Power tab)
sudo systemctl stop tremplin       # stop the service
sudo systemctl start tremplin      # start it again
systemctl status tremplin          # current state
journalctl -u tremplin -f          # follow live logs
```

### CLI troubleshooting

**The service won't start.** Run `journalctl -u tremplin -f` to see the error. Common
causes: wrong serial port, missing Python dependencies (run `uv sync` in the repo
directory), or another process already bound to port 5000.

**Serial adapter not detected.** Run `ls /dev/ttyUSB*` on Pi #1 to list adapters. The
service user must be in the `dialout` group — check with `groups`; if missing, `sudo
usermod -aG dialout <user>` and reboot. (The installer normally handles this.)

**`tremplin.local` unreachable.** See [troubleshooting-tremplin-local-unreachable.md](troubleshooting-tremplin-local-unreachable.md).
