#!/bin/sh
exec swayidle -w \
  timeout 600 "/home/ravi/.config/sway/lock.sh" \
  timeout 900 'swaymsg "output * power off"' \
  resume 'swaymsg "output * power on"' \
  before-sleep "/home/ravi/.config/sway/lock.sh"
