"""Splouch Qt scoreboard — the native TV display for the kiosk Pi.

Replaces the Chromium kiosk that rendered ``/live`` in a browser. It speaks the
same contract every other client speaks (see ``docs/api.md``): fetch ``GET
/config`` once for theme/labels/column visibility, then merge ``update_scoreboard``
frames off ``/ws/scoreboard``.

It lives in this repo so that a given git ref provisions a matching server and
display — ``install.sh server <version>`` and ``install.sh kiosk <version>`` check
out the same code. It must nonetheless treat the server as a *remote peer*: no
imports from ``server/``, no shared process state, nothing but the documented API.

Nothing is re-exported here on purpose. Importing ``scoreboard.app`` pulls in
PySide6, and the pure-logic modules (``theme``, ``fonts``) must stay importable —
and testable — on a machine with no Qt installed, such as CI.
"""
