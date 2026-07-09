#!/bin/sh
# Runs on swayidle's "resume" event (lid reopen / any wake).
#
# Root cause of the black-screen-after-resume bug this works around: the
# panel is eDP-1 on i915 (confirmed via /sys/class/drm - the discrete nouveau
# GPU only owns an unused HDMI port, so it isn't the culprit). A plain
# `swaymsg output * power on` can silently no-op if sway's internal model
# already believes the output is "on" (it just never got the memo that the
# panel's backlight power actually went off) - forcing power off, then on,
# guarantees a real DPMS transition instead of a no-op.
swaymsg 'output * power off'
sleep 0.3
swaymsg 'output * power on'

# bl_power (a distinct kernel attribute from the brightness percentage,
# root-only) is handled earlier by the systemd-sleep hook
# (/usr/lib/systemd/system-sleep/50-backlight-resume.sh), which runs as
# root as part of the actual resume transaction - no permission issue
# there, and it fires deterministically even if this swayidle hook is
# itself delayed by whatever caused the black screen in the first place.

# Restore whatever brightness was active before sleep (before-sleep.sh
# below saves it) - some panels reset to a low default across resume.
if [ -f /tmp/.brightness-before-sleep ]; then
  brightnessctl set "$(cat /tmp/.brightness-before-sleep)" >/dev/null 2>&1
fi
