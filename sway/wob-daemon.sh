#!/bin/sh
# Starts wob once, reading from a long-lived FIFO - the standard wob
# integration pattern. Started once via sway's exec_always; volume
# keybindings (see sway/config) just echo a 0-100 value into the FIFO from
# then on rather than spawning a fresh wob process per keypress, which
# would fight itself over the same layer-shell surface.
WOB_SOCK="$XDG_RUNTIME_DIR/wob.sock"
[ -p "$WOB_SOCK" ] || mkfifo -m 600 "$WOB_SOCK"
tail -f "$WOB_SOCK" | wob -c "$HOME/.config/wob/wob.ini"
