#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C

popup_style="$HOME/.config/waybar/network-popup.css"
popup_match="wofi.*${popup_style}"

if pgrep -u "$USER" -f "$popup_match" >/dev/null; then
  pkill -u "$USER" -f "$popup_match"
  exit 0
fi

nmcli_fast() {
  nmcli --wait 2 "$@"
}

# SSIDs come from nearby broadcast networks (untrusted, attacker-controllable
# text) and get embedded in pango markup below - escape the 3 markup
# metacharacters so a hostile SSID can't break out of its <span> or inject tags.
escape_markup() {
  sed -e 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' <<< "$1"
}

# The sway rule (for_window [app_id="wofi"] ... move position 1538 48)
# only fires at initial map, before wofi's GTK content finishes laying out.
# Measured: wofi's real natural size can differ from --width/--lines, and
# settles within ~300ms - after which sway never moves it again. So one
# corrective move once the window has its final size, using its *actual*
# width, is both necessary and sufficient (no continuous polling needed).
reposition_once() {
  local tries=0 rect w screen_w out_x
  while [ "$tries" -lt 20 ]; do
    rect=$(swaymsg -t get_tree 2>/dev/null | jq -c '[.. | objects | select(.app_id? == "wofi")][0].rect // empty')
    [ -n "$rect" ] && [ "$rect" != "null" ] && break
    tries=$((tries + 1))
    sleep 0.03
  done
  [ -n "${rect:-}" ] && [ "$rect" != "null" ] || return
  w=$(printf '%s' "$rect" | jq -r '.width')
  screen_w=$(swaymsg -t get_outputs 2>/dev/null | jq -r 'map(select(.active))[0].rect.width // 1920')
  out_x=$((screen_w - w - 10))
  # "move absolute position" (not plain "move position", which is relative to
  # the workspace's usable area - inset by gaps + the bar's reserved exclusive
  # zone, which is exactly the source of the drift this function corrects)
  swaymsg "[app_id=\"wofi\"] move absolute position $out_x 48" >/dev/null 2>&1 || true
}

focused_app_id() {
  swaymsg -t get_tree 2>/dev/null \
    | jq -r '[.. | objects | select(.focused? == true)][0].app_id // ""'
}

close_on_focus_loss() {
  # Event-driven: block on sway focus events instead of polling.
  # One initial state check covers the race where focus moved (or never
  # reached wofi) before the subscription started — after that, zero wakeups.
  sleep 0.6
  if [ "$(focused_app_id)" != "wofi" ]; then
    pkill -u "$USER" -f "$popup_match" 2>/dev/null || true
    return
  fi
  swaymsg -t subscribe -m '["window"]' 2>/dev/null \
    | jq --unbuffered -r 'select(.change == "focus") | .container.app_id // ""' \
    | while IFS= read -r app_id; do
        if [ "$app_id" != "wofi" ]; then
          pkill -u "$USER" -f "$popup_match" 2>/dev/null || true
          break
        fi
      done
}

run_popup() {
  reposition_once &
  reposition_pid=$!
  close_on_focus_loss &
  watcher_pid=$!
  "${wofi_cmd[@]}" || true
  # kill the watchers' whole pipelines (swaymsg subscribe would linger otherwise)
  pkill -P "$watcher_pid" 2>/dev/null || true
  kill "$watcher_pid" "$reposition_pid" 2>/dev/null || true
}

wofi_cmd=(
  wofi
  --dmenu
  --normal-window
  --gtk-dark
  --hide-search
  --insensitive
  --allow-markup
  --parse-search
  --no-custom-entry
  --prompt "Wi-Fi"
  --width 380
  --lines 11
  --location top_right
  --xoffset -10
  --yoffset 48
  --style "$popup_style"
)

wifi_device="$(nmcli_fast -t -f DEVICE,TYPE device status | awk -F: '$2 == "wifi" { print $1; exit }')"

if [ -z "${wifi_device:-}" ]; then
  printf 'No Wi-Fi device found\nOpen Network Settings\n' | run_popup >/dev/null
  nm-connection-editor
  exit 0
fi

wifi_state="$(nmcli_fast -t -f WIFI general | cut -d: -f1)"
ip_addr=""
wifi_list=""
active_ssid=""
signal=""

if [ "$wifi_state" = "enabled" ]; then
  ip_addr="$(nmcli_fast -g IP4.ADDRESS device show "$wifi_device" | head -n 1 | cut -d/ -f1)"
  wifi_list="$(
    nmcli_fast -t --escape no -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list --rescan no \
      | awk -F: '
          $2 != "" && !seen[$2]++ {
            print
            if (++count >= 14) exit
          }
        '
  )"
  active_ssid="$(printf '%s\n' "$wifi_list" | awk -F: '$1 == "*" { print $2; exit }')"
  signal="$(printf '%s\n' "$wifi_list" | awk -F: '$1 == "*" { print $3; exit }')"
fi

menu_file="$(mktemp)"
trap 'rm -f "$menu_file"' EXIT

add_item() {
  printf '%s\t%s\n' "$1" "$2" >> "$menu_file"
}

divider() {
  add_item "<span foreground='#5b6472' size='small'>$(escape_markup "$1")</span>" "noop"
}

# --- Row 1: the toggle, mac-style - bold, colored, always first.
# (No pango size= bump here: it overflows #entry's fixed row height and
# clips the text almost entirely - confirmed by screenshot. Bold+color is
# enough differentiation without breaking the layout.) ---
if [ "$wifi_state" = "enabled" ]; then
  add_item "<span foreground='#66d9a6' weight='bold'>󰖩  Wi-Fi        ON</span>" "wifi-off"
else
  add_item "<span foreground='#8b95a5' weight='bold'>󰖪  Wi-Fi        OFF</span>" "wifi-on"
fi

if [ "$wifi_state" = "enabled" ]; then
  # --- Row 2: currently-connected network, shown once here (not repeated
  # further down in "Other Networks" - mirrors how macOS never re-lists the
  # active network in its own submenu) ---
  if [ -n "$active_ssid" ]; then
    divider "Current Network"
    add_item "$(printf '<span foreground=\x27#edf3fb\x27>✓  %s</span>  <span foreground=\x27#5b6472\x27>%s%%</span>' \
      "$(escape_markup "$active_ssid")" "${signal:-0}")" "disconnect"
    add_item "<span foreground='#5b6472'>󰩟  ${ip_addr:-No IPv4 address}</span>" "noop"
  fi

  # --- Row 3: nearby networks, excluding the one already shown above ---
  divider "Other Networks"
  while IFS=: read -r in_use ssid strength security; do
    [ -n "$ssid" ] || continue
    [ "$in_use" = "*" ] && continue   # already shown as "Current Network"
    [ -n "$security" ] && lock="  " || lock=""
    if [ "${strength:-0}" -ge 80 ]; then
      bars="󰤨"
    elif [ "${strength:-0}" -ge 60 ]; then
      bars="󰤥"
    elif [ "${strength:-0}" -ge 40 ]; then
      bars="󰤢"
    else
      bars="󰤟"
    fi
    add_item "$(printf '%s  %s%s  <span foreground=\x27#5b6472\x27>%s%%</span>' \
      "$bars" "$lock" "$(escape_markup "$ssid")" "$strength")" "connect:$ssid"
  done <<< "$wifi_list"
else
  add_item "<span foreground='#5b6472'>Turn Wi-Fi on to see nearby networks</span>" "noop"
fi

# --- Bottom actions, mac-style trailing "Settings…" with ellipsis ---
divider "─────────────────"
add_item "  Rescan Networks" "rescan"
add_item "  Wi-Fi Settings…" "settings"

choice="$(cut -f1 "$menu_file" | run_popup)"
[ -n "$choice" ] || exit 0

action="$(awk -F '\t' -v label="$choice" '$1 == label { print $2; exit }' "$menu_file")"

case "$action" in
  noop)
    ;;
  rescan)
    notify-send -t 2000 "Wi-Fi" "Scanning for networks…"
    nmcli_fast dev wifi rescan
    sleep 1.5
    exec "$0"
    ;;
  disconnect)
    if nmcli_fast device disconnect "$wifi_device"; then
      notify-send "Wi-Fi" "Disconnected"
    else
      notify-send "Wi-Fi" "Failed to disconnect"
    fi
    ;;
  wifi-on)
    nmcli_fast radio wifi on
    exec "$0"
    ;;
  wifi-off)
    nmcli_fast radio wifi off
    ;;
  settings)
    nm-connection-editor
    ;;
  connect:*)
    ssid="${action#connect:}"
    if nmcli_fast -t -f NAME connection show | grep -Fxq "$ssid"; then
      if nmcli_fast connection up "$ssid"; then
        notify-send "Wi-Fi" "Connected to $ssid"
      else
        notify-send "Wi-Fi" "Couldn't connect to $ssid"
      fi
    else
      reposition_once &
      reposition_pid=$!
      password="$(printf '' | wofi --dmenu --normal-window --password --prompt "Password" --width 380 --lines 1 --location top_right --xoffset -10 --yoffset 48 --style "$popup_style" || true)"
      kill "$reposition_pid" 2>/dev/null || true
      [ -n "$password" ] || exit 0
      if nmcli_fast dev wifi connect "$ssid" password "$password"; then
        notify-send "Wi-Fi" "Connected to $ssid"
      else
        notify-send "Wi-Fi" "Couldn't connect to $ssid — check the password"
      fi
    fi
    ;;
esac
