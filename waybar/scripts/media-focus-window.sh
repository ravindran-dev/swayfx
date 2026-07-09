#!/bin/sh
# Focuses the sway window belonging to whichever app playerctl considers
# the current MPRIS player - bound to clicking the waybar media module.
#
# There's no direct "give me this player's window" API, so this chains two
# confirmed-working primitives: a D-Bus bus name -> owning PID
# (org.freedesktop.DBus.GetConnectionUnixProcessID, verified live against
# mako's own bus name), then PID -> window via sway's own `[pid=N] focus`
# criteria (sway's window tree carries each window's pid - confirmed live
# via `swaymsg -t get_tree`). Works for anything where the MPRIS-owning
# process is the same one that opened the window - true for browsers
# (Brave/Chromium own their window and their MPRIS service from the same
# main process) and Spotify.
#
# playerctl's {{playerName}} format field isn't guaranteed to be the exact
# D-Bus bus-name suffix for every player (confirmed only against mako,
# which isn't itself an MPRIS player - never verified against a real
# multi-instance case like a browser's org.mpris.MediaPlayer2.chromium.
# instanceNNNNN naming), so this tries the literal name first and falls
# back to matching any live org.mpris.MediaPlayer2.* bus name that
# contains it, rather than assuming they're always identical.
set -eu

player="$(playerctl metadata --format '{{playerName}}' 2>/dev/null || true)"
if [ -z "$player" ]; then
    notify-send -t 1500 -a "Now Playing" "No active player" "Nothing is currently playing." 2>/dev/null || true
    exit 0
fi

bus_name="org.mpris.MediaPlayer2.$player"
if ! busctl --user status "$bus_name" >/dev/null 2>&1; then
    bus_name="$(busctl --user list 2>/dev/null \
        | awk '{print $1}' \
        | grep -F "org.mpris.MediaPlayer2." \
        | grep -F "$player" \
        | head -1)"
fi

if [ -z "$bus_name" ]; then
    notify-send -t 2000 -a "Now Playing" "Couldn't find that app's window" \
        "playerctl reports \"$player\" but no matching D-Bus service was found." 2>/dev/null || true
    exit 0
fi

pid="$(busctl --user call org.freedesktop.DBus /org/freedesktop/DBus \
  org.freedesktop.DBus GetConnectionUnixProcessID s \
  "$bus_name" 2>/dev/null | awk '{print $2}')"

if [ -z "$pid" ]; then
    notify-send -t 2000 -a "Now Playing" "Couldn't find that app's window" \
        "No process owns $bus_name." 2>/dev/null || true
    exit 0
fi

if ! swaymsg "[pid=$pid] focus" 2>/dev/null | grep -q '"success": *true'; then
    notify-send -t 2000 -a "Now Playing" "Couldn't focus that window" \
        "$player (pid $pid) has no visible sway window." 2>/dev/null || true
fi
