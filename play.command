#!/bin/bash
# play.command — DroneWar launcher for macOS
# Double-click this file to start the game.
# macOS runs .command files directly in Terminal — no signing required.

# Move to the directory containing this script
cd "$(dirname "$0")"

echo ""
echo "════════════════════════════════════════"
echo "  DRONEWAR"
echo "════════════════════════════════════════"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "  ERROR: Python 3 not found."
    echo "  Install from https://www.python.org/downloads/"
    read -p "  Press Enter to close..."
    exit 1
fi

# Install Flask if needed (silently)
python3 -c "import flask" 2>/dev/null || {
    echo "  Installing Flask (first run only)..."
    pip3 install flask --quiet
}

echo "  Starting server..."
echo "  Opening game in your browser."
echo "  Close this window to quit."
echo ""

python3 server.py
