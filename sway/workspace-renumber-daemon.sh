#!/bin/sh
# Starts workspace-renumber.py once. flock, not pkill+restart: this
# process runs as `python3 workspace-renumber.py`, whose actual process
# name is just "python3" - pkill -x python3 would kill every unrelated
# python3 process on the system, and pkill -f to match the full command
# line instead was confirmed live to hang indefinitely inside sway's
# exec_always (see the matching comment in volume-osd-daemon.sh). A
# non-blocking flock sidesteps needing to identify or signal any existing
# instance at all.
LOCK="$XDG_RUNTIME_DIR/workspace-renumber.lock"
exec 9>"$LOCK"
flock -n 9 || exit 0

exec python3 "$HOME/.config/sway/workspace-renumber.py"
