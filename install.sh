#!/usr/bin/env bash
# Layla installer (Linux / macOS) — one command, powered by uv.
#
# uv fetches a standalone Python and installs every dependency from prebuilt CPU wheels
# (no compiler, no system Python, no admin), then provisions a model and self-tests.
# This is the canonical install path; it forwards to install/bootstrap.sh.
#
#   git clone https://github.com/PapaKoftes/Layla.git && cd Layla && ./install.sh
#
exec "$(cd "$(dirname "$0")" && pwd)/install/bootstrap.sh" "$@"
