"""
launcher.py — DroneWar standalone launcher
Used by the PyInstaller .app / .exe builds and can be run directly.
"""

import os
import socket
import sys
import threading
import time


def find_free_port(start: int = 5000) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def open_browser(url: str) -> None:
    """
    Open a browser tab pointing at url.
    
    macOS unsigned apps get error -47 (errAEWaitCanceled) when they try
    to send Apple Events to other apps — which is what 'open url' does.
    
    We work around this by:
    1. Trying webbrowser.open() — on macOS this ultimately calls 'open'
       but may work depending on sandbox context.
    2. If that fails, writing a tiny redirect HTML file to /tmp and
       opening the FILE (file:// URLs open without Apple Events).
    3. If that fails, printing the URL clearly so the user can copy it.
    """
    time.sleep(1.5)  # let Flask bind first

    # Attempt 1: webbrowser module
    try:
        import webbrowser
        webbrowser.open(url)
        return
    except Exception:
        pass

    # Attempt 2: write a redirect file to /tmp and open that
    # Opening a local file doesn't require Apple Events permission
    try:
        import tempfile
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="0; url={url}">
<title>DroneWar — launching...</title>
</head>
<body>
<p>Opening DroneWar... <a href="{url}">Click here if it doesn't redirect.</a></p>
<script>window.location.href = "{url}";</script>
</body>
</html>"""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False, prefix='dronewar_'
        ) as f:
            f.write(html)
            tmp_path = f.name

        if sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', tmp_path])
            return
        elif sys.platform == 'win32':
            os.startfile(tmp_path)
            return
    except Exception:
        pass

    # Attempt 3: platform subprocess fallback
    try:
        import subprocess
        if sys.platform == 'win32':
            subprocess.Popen(f'start "" "{url}"', shell=True)
        else:
            for cmd in ['xdg-open', 'gnome-open']:
                try:
                    subprocess.Popen([cmd, url])
                    return
                except FileNotFoundError:
                    continue
    except Exception:
        pass

    # All failed — URL is printed in the banner, user opens manually
    print(f"\n  >>> Could not open browser automatically.")
    print(f"  >>> Please open this URL manually: {url}\n", flush=True)


def main():
    # Set working directory so Flask can find static/
    if getattr(sys, 'frozen', False):
        # Running inside PyInstaller bundle
        bundle_dir = sys._MEIPASS  # type: ignore[attr-defined]
        os.chdir(bundle_dir)
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    port = find_free_port()
    url  = f"http://127.0.0.1:{port}"

    from server import app  # noqa — import here for PyInstaller tracing

    print(f"\n{'═'*54}")
    print(f"  DRONEWAR  —  Tactical UAV Warfare Simulation")
    print(f"{'═'*54}")
    print(f"")
    print(f"  Game URL:  {url}")
    print(f"")
    print(f"  Opening in your browser...")
    print(f"  If the browser doesn't open, go to the URL above.")
    print(f"  Close this window to quit.")
    print(f"{'═'*54}\n", flush=True)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
