#!/bin/sh
# Runs before both idle-lock and actual system sleep. Saves brightness so
# resume-fix.sh can restore it (some panels reset backlight across resume).
brightnessctl get > /tmp/.brightness-before-sleep 2>/dev/null
exec /home/ravi/.config/sway/lock.sh
