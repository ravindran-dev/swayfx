#!/bin/sh
# Lid-close handler - locks and blanks the display WITHOUT suspending.
#
# Real ACPI/s2idle suspend is unsafe on this hardware: the boot/root
# filesystem lives on an external USB SSD behind a JMicron bridge chip
# (confirmed via `findmnt` + `lsblk` - /dev/sda, TRAN=usb). journalctl
# showed a real suspend cycle from a previous boot with an 11-minute gap
# between "PM: suspend entry" and "PM: suspend exit" - consistent with the
# USB controller failing to cleanly re-enumerate the boot disk on resume,
# not a normal sleep duration. If that hang happens mid-write, it risks
# corrupting the filesystem the whole system is running from.
#
# This trades some idle battery life for the system staying fully alive
# (and the boot disk's USB controller never being asked to suspend at
# all) in exchange for actually working every single time.
swaylock -C /home/ravi/.config/swaylock/config &
sleep 0.3
swaymsg 'output * power off'
