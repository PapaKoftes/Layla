#!/usr/bin/env bash
# Double-clickable macOS installer. Finder runs this in Terminal; it just calls
# the uv bootstrap (installs Python + everything, provisions a model, self-tests).
# If double-clicking is blocked by Gatekeeper: right-click -> Open, or run
#   chmod +x "install/Install Layla.command"
cd "$(dirname "$0")/.." || exit 1
./install/bootstrap.sh "$@"
status=$?
echo ""
echo "Press Return to close this window."
read -r _
exit $status
