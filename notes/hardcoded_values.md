# Hardcoded values — potential settings candidates

Reviewed 2026-05-10. Values already in settings are marked ✓.

| Value | Location | What it does | Verdict |
| --- | --- | --- | --- |
| `30s` timer interval | `scoreboard.html` `setInterval(on_timer, 30000)` | Sends scoreboard to Splash if no CTS data arrives within the window — effectively a connection-lost timeout | Too technical; the CTS console sends data constantly so this only fires on disconnection |
| `10s` `scoreboard_paused` in `mode_to_intro()` | `scoreboard.html` line ~152 | Brief lock after switching to Intro mode to prevent the state machine from immediately switching away | Pure implementation detail, no user benefit |
| `10s` `scoreboard_paused` in `mode_to_results()` | `scoreboard.html` line ~190 | Same lock after switching to Results mode | Pure implementation detail |
| `{1:0, 2:400, 3:800}` ms podium delays | `scoreboard.html` `highlight_podium()` | Staggered animation: gold appears first, silver 400ms later, bronze 800ms later | Cosmetic tweak, not worth a settings field |
| `9600 baud` serial speed | `Tremplin.py` `serial.Serial(..., 9600)` | CTS Gen6 serial port baud rate | Fixed by hardware protocol — not configurable |
| Podium colours | `scoreboard_style.css` / Theme tab | Row highlight colours for 1st/2nd/3rd | ✓ Already in Theme tab |
| Number of lanes | `settings.json` / Meet Setup tab | 4, 6, or 8 lanes | ✓ Already in Meet Setup |
| Intro → Splash timeout | `settings.json` / Flow tab | Seconds before returning to Splash after a new event/heat if race doesn't start | ✓ Already in Flow tab |
| Results → Splash timeout | `settings.json` / Flow tab | Seconds before returning to Splash after results are shown | ✓ Already in Flow tab |
