#!/bin/sh
# Feeds the current sink volume (or 0 if muted) into the volume OSD's FIFO
# - called after every volume/mute keybinding in sway/config so the OSD
# reflects the real post-change state rather than assuming the delta
# applied cleanly (it already clamps at 0/100 on its own, this just reads
# back whatever pactl settled on).
set -eu
OSD_SOCK="$XDG_RUNTIME_DIR/volume-osd.sock"
[ -p "$OSD_SOCK" ] || exit 0

mute="$(pactl get-sink-mute @DEFAULT_SINK@ | awk '{print $2}')"
if [ "$mute" = "yes" ]; then
  echo 0 > "$OSD_SOCK"
else
  vol="$(pactl get-sink-volume @DEFAULT_SINK@ | awk -F'/' '/Volume:/{gsub(/[ %]/,"",$2); print $2; exit}')"
  echo "${vol:-0}" > "$OSD_SOCK"
fi
