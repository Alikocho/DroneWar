"""
launcher.py
===========
Standalone launcher for DroneWar.
Starts the Flask server on a free port and opens a browser tab.
Used by the PyInstaller .app / .exe builds.

Run directly:
    python launcher.py
"""

import os
import socket
import sys
import threading
import time
import webbrowser


def find_free_port(start: int = 5000, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main():
    # When frozen by PyInstaller, fix the working directory so Flask
    # can find static/ relative to the bundle.
    if getattr(sys, "frozen", False):
        bundle_dir = sys._MEIPASS          # type: ignore[attr-defined]
        os.chdir(bundle_dir)

    port = find_free_port()
    url  = f"http://127.0.0.1:{port}"

    # Import here so PyInstaller can trace the dependency
    from server import app

    print(f"\n{'═'*52}")
    print(f"  DRONEWAR")
    print(f"  Starting server on {url}")
    print(f"  Close this window to quit.")
    print(f"{'═'*52}\n")

    # Open browser after a short delay to let Flask bind
    def _open():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
