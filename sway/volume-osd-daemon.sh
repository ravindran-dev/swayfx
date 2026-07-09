#!/bin/sh
# Starts the volume OSD renderer once, reading from a long-lived FIFO -
# same `tail -f fifo | consumer` pattern wob itself used (see
# volume-osd-gtk.py's docstring for why wob was replaced: it can't round
# its own corners, and swayfx can't do it for a layer-shell surface's
# content either). Started once via sway's exec_always; volume keybindings
# (see sway/config) just echo a 0-100 value into the FIFO from then on
# rather than spawning a fresh renderer per keypress.
#
# flock, not pkill+restart: this used to pkill any existing instance
# before starting a fresh one on every sway reload (matching how waybar
# gets restarted to pick up config/style changes) - but this daemon's
# behavior lives entirely in volume-osd-gtk.py, not in anything sway
# reload would change, so there's nothing to gain from restarting it, and
# real risk in trying to: matching it by exact process name doesn't work
# (it runs as `python3 volume-osd-gtk.py`, whose actual process name is
# just "python3" - pkill -x python3 would kill every unrelated python3
# process on the system), and `pkill -f` to match the full command line
# instead was confirmed live to hang indefinitely in this exact
# exec_always context (see the comment on this line in sway/config). A
# non-blocking flock sidesteps needing to identify or signal the old
# process at all: if one's already running and holding the lock, this
# invocation just exits immediately instead of racing or duplicating it.
LOCK="$XDG_RUNTIME_DIR/volume-osd-daemon.lock"
exec 9>"$LOCK"
flock -n 9 || exit 0

OSD_SOCK="$XDG_RUNTIME_DIR/volume-osd.sock"
[ -p "$OSD_SOCK" ] || mkfifo -m 600 "$OSD_SOCK"
tail -f "$OSD_SOCK" | python3 "$HOME/.config/sway/volume-osd-gtk.py"
