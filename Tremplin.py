#!/usr/bin/env python3
"""Backwards-compatibility shim for the pre-restructure entrypoint.

The app now lives in ``server/app.py`` and is launched as ``app:app`` with
``WorkingDirectory=<repo>/server`` (see install.sh). Installs created before the
repo was reorganised, however, still run a systemd unit generated with the old
values::

    WorkingDirectory=<repo>
    ExecStart=<venv>/uvicorn Tremplin:app ...

An in-app "Update" (or a plain ``git pull``) swaps the files but cannot rewrite
that unit: only install.sh writes it, and the running updater has no privilege
to touch ``/etc/systemd``. Without this shim, the next ``systemctl restart``
would try to import a ``Tremplin`` module that no longer exists and the service
would crash-loop.

This file keeps ``Tremplin:app`` resolvable from the repo root by putting
``server/`` on ``sys.path`` and re-exporting the FastAPI app. Re-running
``install.sh server`` regenerates the unit to ``app:app``, after which this shim
is no longer used and may be removed in a future release.
"""
import os
import sys

_SERVER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server')
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# Nudge the operator (visible in journalctl) toward regenerating the unit.
print('[tremplin] started via legacy Tremplin.py shim — re-run install.sh '
      'server to update the systemd unit to app:app.', file=sys.stderr)

from app import app  # noqa: E402  (re-exported so `uvicorn Tremplin:app` works)

__all__ = ['app']


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)
