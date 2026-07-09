#!/bin/sh
# Feeds the current sink volume (or 0 if muted) into wob's FIFO - called
# after every volume/mute keybinding in sway/config so the OSD reflects
# the real post-change state rather than assuming the delta applied
# cleanly (it already clamps at 0/100 on its own, this just reads back
# whatever pactl settled on).
set -eu
WOB_SOCK="$XDG_RUNTIME_DIR/wob.sock"
[ -p "$WOB_SOCK" ] || exit 0

mute="$(pactl get-sink-mute @DEFAULT_SINK@ | awk '{print $2}')"
if [ "$mute" = "yes" ]; then
  echo 0 > "$WOB_SOCK"
else
  vol="$(pactl get-sink-volume @DEFAULT_SINK@ | awk -F'/' '/Volume:/{gsub(/[ %]/,"",$2); print $2; exit}')"
  echo "${vol:-0}" > "$WOB_SOCK"
fi
