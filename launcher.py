"""
launcher.py
===========
Standalone launcher for DroneWar.
Starts the Flask server on a free port and opens the game in a browser.
Used by the PyInstaller .app / .exe builds.

Run directly:
    python launcher.py
"""

import os
import socket
import sys
import threading
import time


def find_free_port(start: int = 5000, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def open_browser(url: str) -> None:
    """
    Open a browser tab. Tries multiple approaches in order of reliability.
    Error -47 (errAEWaitCanceled) from 'open' on macOS means the process
    lacks permission to launch other apps — fall through to webbrowser module.
    """
    time.sleep(1.5)  # let Flask bind before the browser requests the page

    # Try 1: Python's webbrowser module — works on all platforms,
    # doesn't require subprocess permissions.
    try:
        import webbrowser
        webbrowser.open(url)
        return
    except Exception:
        pass

    # Try 2: platform-native fallback (subprocess)
    try:
        import subprocess
        if sys.platform == "darwin":
            subprocess.call(["open", url])
        elif sys.platform == "win32":
            subprocess.Popen(f'start "" "{url}"', shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception:
        pass
    # If everything fails the URL is printed in the banner — user can open manually.


def main():
    # When frozen by PyInstaller, set cwd to the bundle so server can find static/
    if getattr(sys, "frozen", False):
        os.chdir(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    port = find_free_port()
    url  = f"http://127.0.0.1:{port}"

    from server import app  # noqa: import inside main for PyInstaller tracing

    banner = f"""
{'═'*54}
  DRONEWAR
{'═'*54}

  Game running at:

      {url}

  Opening in your browser now...
  If the browser doesn't open, copy the URL above.
  Close this window (Ctrl+C) to stop the server.
{'═'*54}
"""
    print(banner, flush=True)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
