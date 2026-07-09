#!/usr/bin/env bash
# Searchable sway keybindings library: reads this user's own sway config,z
# groups every `bindsym` under its nearest `### SECTION` heading, and shows
# it in wofi (fuzzy search + case-insensitive already on globally).
set -euo pipefail

config="$HOME/.config/sway/config"

if [[ ! -r "$config" ]]; then
  notify-send "Keybindings" "Cannot read $config"
  exit 1
fi

list="$(
  awk '
    /^[ \t]*###/ {
      line = $0
      sub(/^[ \t]*###[ \t]*/, "", line)
      section = line
      next
    }
    /^[ \t]*bindsym/ {
      line = $0
      sub(/^[ \t]+/, "", line)
      sub(/^bindsym[ \t]+/, "", line)
      gsub(/[ \t]+/, " ", line)
      split(line, parts, " ")
      key = parts[1]
      rest = line
      sub(/^[^ ]+ /, "", rest)
      printf "[%-20s] %-24s -> %s\n", (section == "" ? "-" : section), key, rest
    }
  ' "$config"
)"

chosen="$(printf '%s\n' "$list" | wofi --dmenu -i -p "Search keybindings (${config##*/})" \
  --width 640 --lines 11 --location center \
  --style "$HOME/.config/wofi/style.css" || true)"

[[ -n "$chosen" ]] || exit 0

# Selecting an entry copies its keybind to the clipboard (bounded by "] "
# and " -> ", so this holds regardless of spaces in the section name).
key="$(printf '%s' "$chosen" | sed -E 's/^\[[^]]*\][ \t]*//; s/[ \t]*->.*$//')"
printf '%s' "$key" | wl-copy
notify-send "Copied" "$key"
