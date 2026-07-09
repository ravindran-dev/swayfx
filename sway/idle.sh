#!/bin/sh
exec swayidle -w \
  timeout 600 "/home/ravi/.config/sway/lock.sh" \
  timeout 900 'swaymsg "output * power off"' \
  resume "/home/ravi/.config/sway/resume-fix.sh" \
  before-sleep "/home/ravi/.config/sway/before-sleep.sh"
