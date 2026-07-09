#!/usr/bin/env bash
# Clipboard history picker for $mod+v. cliphist itself is already running
# (wl-paste --type text --watch cliphist store, started from sway/config) -
# this is just the picker UI on top of it.
set -euo pipefail

export LC_ALL=C

popup_match="wofi --conf.*clipboard-config"

if pgrep -u "$USER" -f "$popup_match" >/dev/null; then
  pkill -u "$USER" -f "$popup_match"
  exit 0
fi

# Keyboard-triggered (not a waybar button click) - centered like the app
# launcher, so there's no "which button was this near" question to answer.
#
# Uses a dedicated config file (wofi/clipboard-config), not --width/--lines/
# --define CLI flags on top of the shared wofi/config: confirmed live that
# the shared config's height=420 was overriding dynamic_lines entirely,
# producing a tall box with empty space below only 3 entries. The dedicated
# config sets dynamic_lines=true with no height= line at all, so it actually
# shrinks to fit - and lines=10 there is a cap, switching to scrolling once
# history exceeds it, not a fixed reserved size.
chosen="$(cliphist list | wofi --conf "$HOME/.config/wofi/clipboard-config" \
  --style "$HOME/.config/wofi/style.css" || true)"

[ -n "$chosen" ] || exit 0

printf '%s' "$chosen" | cliphist decode | wl-copy
notify-send -t 1500 "Clipboard" "Copied - press your paste key to insert it"
