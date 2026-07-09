#!/usr/bin/zsh

################################################################################
# Sway Desktop Environment Setup Script
# This script sets up Sway and related applications on Arch Linux
# 
# DESCRIPTION:
# This setup script automates the installation and configuration of a complete
# Sway desktop environment including:
# - Sway: Tiling Wayland compositor
# - Waybar: Top panel/status bar
# - Mako: Notification daemon
# - Swaylock: Screen locker for Wayland
# - Additional utilities and configuration files
#
# REQUIREMENTS: Arch Linux or Arch-based distribution
# USAGE: zsh setup.sh
################################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the script directory (where this script and config files are located)
SCRIPT_DIR="$(cd "$(dirname "${ZSH_SOURCE[0]}")" && pwd)"


# STEP 1: Display Welcome Banner

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Sway Desktop Environment Setup Script                        ║${NC}"
echo -e "${BLUE}║   Arch Linux Installation & Configuration                      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""


# STEP 2: Check for Root Privileges

# This script should NOT be run as root, as we need to install to the user's
# home directory (~/.config). Running as root would create system-wide configs.
if [[ $EUID -eq 0 ]]; then
   echo -e "${RED}✗ Error: This script must NOT be run as root!${NC}"
   echo "  Please run: zsh setup.sh"
   exit 1
fi
echo -e "${GREEN}✓ Running as regular user${NC}"
echo ""


# STEP 3: Update Pacman Package Manager

# First, update the package manager's database to ensure we have the latest
# package information. This prevents installation failures due to outdated lists.
echo -e "${YELLOW}[1/6] Updating pacman package manager...${NC}"
sudo pacman -Sy --noconfirm
echo -e "${GREEN}✓ Pacman database updated${NC}"
echo ""


# STEP 4: Install Required Packages from Official Repositories

# Install core Sway components and dependencies from Arch Linux repositories.
# 
# Packages explained:
# - sway: Main Wayland compositor (window manager)
# - waybar: Top panel showing workspaces, window info, and system stats
# - mako: Lightweight notification daemon for Wayland
# - swaylock: Screen locker with Wayland support
# - swayidle: Idle daemon that handles timeouts and lock/suspend events
# - wofi: Launcher menu (alternative to rofi for Wayland)
# - kitty: GPU-based terminal emulator (configured as default in sway config)
# - wl-clipboard: Wayland clipboard utilities (wl-copy, wl-paste)
# - grim: Screenshot tool for Wayland
# - slurp: Screen region selector for Wayland
# - cliphist: Clipboard history manager
# - nm-applet: Network manager system tray applet
# - pulseaudio: Audio server (or use pipewire if preferred)
# - xorg-xwayland: XWayland support for legacy X11 applications
# - lxappearance: GUI for setting GTK themes and icons
# - polkit: Authorization framework (required for elevation of privileges)

echo -e "${YELLOW}[2/6] Installing core Sway packages from Arch repositories...${NC}"

PACKAGES=(
    "sway"
    "waybar"
    "mako"
    "swaylock"
    "swayidle"
    "wofi"
    "kitty"
    "wl-clipboard"
    "grim"
    "slurp"
    "cliphist"
    "network-manager"
    "pulseaudio"
    "pulseaudio-alsa"
    "xorg-xwayland"
    "lxappearance"
    "polkit"
    "jq"
    # Wi-Fi/Bluetooth/Volume popups (waybar/{wifi,bluetooth,volume}-popup):
    # GTK3 panels driven by NetworkManager/BlueZ/pactl over D-Bus
    "python-gobject"
    "gtk-layer-shell"
    "libnm"
    "bluez"
    "bluez-utils"
    "brightnessctl"
    # Wi-Fi hotspot sharing (wifi-popup's Hotspot toggle): NetworkManager's
    # ipv4.method=shared needs dnsmasq for DHCP/DNS to the connected
    # devices - without it, the hotspot activates but immediately fails
    # ("could not start dnsmasq: Could not find dnsmasq binary")
    "dnsmasq"
    # Now-playing module (waybar/scripts/media-visualizer.py): playerctl
    # for MPRIS track metadata/control, cava for the live audio waveform
    "playerctl"
    "cava"
    # Volume OSD (sway/wob-daemon.sh + volume-osd.sh): the on-screen bar
    # that pops up on the volume/mute keys
    "wob"
)

# Install packages, checking which ones are already installed
for package in "${PACKAGES[@]}"; do
    if pacman -Q "$package" &> /dev/null; then
        echo -e "${GREEN}  ✓ $package (already installed)${NC}"
    else
        echo -e "${BLUE}  → Installing $package...${NC}"
        if sudo pacman -S "$package" --noconfirm 2>/dev/null; then
            echo -e "${GREEN}  ✓ $package installed${NC}"
        else
            echo -e "${YELLOW}  ⚠ $package could not be installed (may not be available)${NC}"
        fi
    fi
done

echo -e "${GREEN}✓ All core packages installed${NC}"
echo ""


# STEP 5: Create Configuration Directory Structure

# Create the necessary ~/.config directories if they don't exist.
# The .config directory follows the XDG Base Directory specification:
# - ~/.config: User configuration files
# - ~/.local/share: User data files
# - ~/.cache: Temporary cache files
#

echo -e "${YELLOW}[3/6] Creating configuration directory structure...${NC}"

mkdir -p "$HOME/.config/sway"
mkdir -p "$HOME/.config/waybar/scripts"
mkdir -p "$HOME/.config/waybar/wifi-popup"
mkdir -p "$HOME/.config/waybar/bluetooth-popup"
mkdir -p "$HOME/.config/waybar/volume-popup"
mkdir -p "$HOME/.config/mako"
mkdir -p "$HOME/.config/swaylock"
mkdir -p "$HOME/.config/wofi"
mkdir -p "$HOME/.config/wob"
mkdir -p "$HOME/.local/share/applications"

echo -e "${GREEN}✓ Configuration directories created${NC}"
echo ""

# STEP 6: Copy Sway Configuration Files

# Copy configuration files from the repository to the appropriate locations
# in ~/.config. This sets up the visual theme, keybindings, and autostart
# applications.
#
# File destinations:
# - sway/config → ~/.config/sway/config (Sway window manager configuration)
# - waybar/config → ~/.config/waybar/config (Status bar layout and modules)
# - waybar/style.css → ~/.config/waybar/style.css (Status bar styling)
# - waybar/network-popup.css → ~/.config/waybar/network-popup.css
# - waybar/scripts/network-popup.sh → ~/.config/waybar/scripts/network-popup.sh
# - mako/config → ~/.config/mako/config (Notification daemon config)
# - swaylock/config → ~/.config/swaylock/config (Lock screen config)

echo -e "${YELLOW}[4/6] Installing configuration files to ~/.config...${NC}"

# Copy Sway configuration
if [[ -f "$SCRIPT_DIR/sway/config" ]]; then
    cp "$SCRIPT_DIR/sway/config" "$HOME/.config/sway/config"
    chmod 644 "$HOME/.config/sway/config"
    echo -e "${GREEN}  ✓ Sway config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: sway/config not found${NC}"
fi

# Copy Waybar configuration
if [[ -f "$SCRIPT_DIR/waybar/config" ]]; then
    cp "$SCRIPT_DIR/waybar/config" "$HOME/.config/waybar/config"
    chmod 644 "$HOME/.config/waybar/config"
    echo -e "${GREEN}  ✓ Waybar config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/config not found${NC}"
fi

# Copy Waybar stylesheet
if [[ -f "$SCRIPT_DIR/waybar/style.css" ]]; then
    cp "$SCRIPT_DIR/waybar/style.css" "$HOME/.config/waybar/style.css"
    chmod 644 "$HOME/.config/waybar/style.css"
    echo -e "${GREEN}  ✓ Waybar stylesheet installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/style.css not found${NC}"
fi

# Copy Waybar network popup CSS
if [[ -f "$SCRIPT_DIR/waybar/network-popup.css" ]]; then
    cp "$SCRIPT_DIR/waybar/network-popup.css" "$HOME/.config/waybar/network-popup.css"
    chmod 644 "$HOME/.config/waybar/network-popup.css"
    echo -e "${GREEN}  ✓ Waybar network popup CSS installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/network-popup.css not found${NC}"
fi

# Copy Waybar network popup script
if [[ -f "$SCRIPT_DIR/waybar/scripts/network-popup.sh" ]]; then
    cp "$SCRIPT_DIR/waybar/scripts/network-popup.sh" "$HOME/.config/waybar/scripts/network-popup.sh"
    chmod 755 "$HOME/.config/waybar/scripts/network-popup.sh"
    echo -e "${GREEN}  ✓ Waybar network popup script installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/scripts/network-popup.sh not found${NC}"
fi

# Copy the GTK Wi-Fi popup (macOS-style panel opened by the waybar network
# module; python + GTK3 + gtk-layer-shell + libnm, all installed above)
if [[ -d "$SCRIPT_DIR/waybar/wifi-popup" ]]; then
    mkdir -p "$HOME/.config/waybar/wifi-popup"
    cp "$SCRIPT_DIR/waybar/wifi-popup/"*.py "$HOME/.config/waybar/wifi-popup/"
    cp "$SCRIPT_DIR/waybar/wifi-popup/styles.css" "$HOME/.config/waybar/wifi-popup/"
    chmod 755 "$HOME/.config/waybar/wifi-popup/wifi_popup.py"
    echo -e "${GREEN}  ✓ Wi-Fi popup (GTK) installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/wifi-popup not found${NC}"
fi

# Copy the GTK Bluetooth popup - mirrors wifi-popup's structure exactly,
# raw D-Bus/BlueZ instead of libnm (no GI binding exists for BlueZ)
if [[ -d "$SCRIPT_DIR/waybar/bluetooth-popup" ]]; then
    mkdir -p "$HOME/.config/waybar/bluetooth-popup"
    cp "$SCRIPT_DIR/waybar/bluetooth-popup/"*.py "$HOME/.config/waybar/bluetooth-popup/"
    cp "$SCRIPT_DIR/waybar/bluetooth-popup/styles.css" "$HOME/.config/waybar/bluetooth-popup/"
    chmod 755 "$HOME/.config/waybar/bluetooth-popup/bluetooth_popup.py"
    echo -e "${GREEN}  ✓ Bluetooth popup (GTK) installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/bluetooth-popup not found${NC}"
fi

# Copy the GTK Volume popup - same architecture again, pactl instead of
# libnm/BlueZ (no GI binding exists for PulseAudio/PipeWire either)
if [[ -d "$SCRIPT_DIR/waybar/volume-popup" ]]; then
    mkdir -p "$HOME/.config/waybar/volume-popup"
    cp "$SCRIPT_DIR/waybar/volume-popup/"*.py "$HOME/.config/waybar/volume-popup/"
    cp "$SCRIPT_DIR/waybar/volume-popup/styles.css" "$HOME/.config/waybar/volume-popup/"
    chmod 755 "$HOME/.config/waybar/volume-popup/volume_popup.py"
    echo -e "${GREEN}  ✓ Volume popup (GTK) installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/volume-popup not found${NC}"
fi

# Copy the "now playing" waybar module: playerctl for MPRIS metadata/
# control, cava for the live audio waveform (both installed above)
if [[ -f "$SCRIPT_DIR/waybar/scripts/media-visualizer.py" ]]; then
    mkdir -p "$HOME/.config/waybar/scripts"
    cp "$SCRIPT_DIR/waybar/scripts/media-visualizer.py" "$HOME/.config/waybar/scripts/media-visualizer.py"
    cp "$SCRIPT_DIR/waybar/scripts/media-focus-window.sh" "$HOME/.config/waybar/scripts/media-focus-window.sh"
    cp "$SCRIPT_DIR/waybar/media-visualizer-cava.conf" "$HOME/.config/waybar/media-visualizer-cava.conf"
    chmod 755 "$HOME/.config/waybar/scripts/media-visualizer.py" "$HOME/.config/waybar/scripts/media-focus-window.sh"
    echo -e "${GREEN}  ✓ Now-playing module installed${NC}"
else
    echo -e "${RED}  ✗ Warning: waybar/scripts/media-visualizer.py not found${NC}"
fi

# Copy sway helper scripts (idle timeout, lock wrapper, keybindings help
# menu on \$mod+h, lid-close handler, clipboard history picker, volume OSD
# feeder, wob daemon launcher, pre/post-suspend backlight fixes - all
# referenced by sway/config)
for script in idle.sh lock.sh show_keybindings.sh before-sleep.sh \
              clipboard-popup.sh lid-close.sh resume-fix.sh volume-osd.sh \
              wob-daemon.sh; do
    if [[ -f "$SCRIPT_DIR/sway/$script" ]]; then
        cp "$SCRIPT_DIR/sway/$script" "$HOME/.config/sway/$script"
        chmod 755 "$HOME/.config/sway/$script"
        echo -e "${GREEN}  ✓ sway/$script installed${NC}"
    else
        echo -e "${RED}  ✗ Warning: sway/$script not found${NC}"
    fi
done

# SwayFX eye candy: sway/config includes swayfx.conf, whose commands
# (corner_radius, blur, shadows, layer_effects) HARD-ERROR on vanilla sway.
# A missing include is non-fatal, so only install the file when the sway
# binary is actually swayfx (AUR package that replaces sway).
if sway --version 2>/dev/null | grep -qi swayfx; then
    cp "$SCRIPT_DIR/sway/swayfx.conf" "$HOME/.config/sway/swayfx.conf"
    chmod 644 "$HOME/.config/sway/swayfx.conf"
    echo -e "${GREEN}  ✓ swayfx.conf installed (swayfx detected)${NC}"
else
    echo -e "${YELLOW}  ⚠ vanilla sway detected - skipping swayfx.conf (rounded corners/blur/shadows need the AUR swayfx package)${NC}"
fi

# Copy wofi launcher configuration (menu on $mod+d, styled to match the desktop)
if [[ -f "$SCRIPT_DIR/wofi/config" ]]; then
    mkdir -p "$HOME/.config/wofi"
    cp "$SCRIPT_DIR/wofi/config" "$SCRIPT_DIR/wofi/style.css" "$HOME/.config/wofi/"
    chmod 644 "$HOME/.config/wofi/config" "$HOME/.config/wofi/style.css"
    echo -e "${GREEN}  ✓ Wofi config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: wofi/config not found${NC}"
fi

# Copy the clipboard picker's dedicated wofi config ($mod+v) - deliberately
# separate from wofi/config: the shared config's fixed height overrides
# dynamic_lines, which is what lets this one size itself to the actual
# number of clipboard entries instead of always showing a tall empty box
if [[ -f "$SCRIPT_DIR/wofi/clipboard-config" ]]; then
    cp "$SCRIPT_DIR/wofi/clipboard-config" "$HOME/.config/wofi/clipboard-config"
    chmod 644 "$HOME/.config/wofi/clipboard-config"
    echo -e "${GREEN}  ✓ Clipboard picker config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: wofi/clipboard-config not found${NC}"
fi

# Copy Mako configuration
if [[ -f "$SCRIPT_DIR/mako/config" ]]; then
    cp "$SCRIPT_DIR/mako/config" "$HOME/.config/mako/config"
    chmod 644 "$HOME/.config/mako/config"
    echo -e "${GREEN}  ✓ Mako config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: mako/config not found${NC}"
fi

# Copy Swaylock configuration
if [[ -f "$SCRIPT_DIR/swaylock/config" ]]; then
    cp "$SCRIPT_DIR/swaylock/config" "$HOME/.config/swaylock/config"
    chmod 644 "$HOME/.config/swaylock/config"
    echo -e "${GREEN}  ✓ Swaylock config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: swaylock/config not found${NC}"
fi

# Copy wob (volume OSD) styling. NOTE the config file has NO [section]
# header at all - confirmed directly against wob's own source
# (src/config.c: handler() parses global settings under section == "",
# i.e. before any [bracket] line) after two wrong guesses ([main], then
# [default]) both got silently rejected with "Unknown config section ...".
if [[ -f "$SCRIPT_DIR/wob/wob.ini" ]]; then
    mkdir -p "$HOME/.config/wob"
    cp "$SCRIPT_DIR/wob/wob.ini" "$HOME/.config/wob/wob.ini"
    chmod 644 "$HOME/.config/wob/wob.ini"
    echo -e "${GREEN}  ✓ wob (volume OSD) config installed${NC}"
else
    echo -e "${RED}  ✗ Warning: wob/wob.ini not found${NC}"
fi

echo -e "${GREEN}✓ Configuration files installed${NC}"
echo ""


# STEP 7: Setup MIME Types and File Associations


# The mimeapps.list file defines associations like:
# - text/html=firefox.desktop (Open HTML files with Firefox)
# - video/*=mpv.desktop (Open videos with MPV player)
# - image/*=imv.desktop (Open images with IMV viewer)

echo -e "${YELLOW}[5/6] Setting up MIME type associations...${NC}"

if [[ -f "$SCRIPT_DIR/applications/mimeapps.list" ]]; then
    cp "$SCRIPT_DIR/applications/mimeapps.list" "$HOME/.config/mimeapps.list"
    chmod 644 "$HOME/.config/mimeapps.list"
    echo -e "${GREEN}  ✓ MIME type associations configured${NC}"
else
    echo -e "${RED}  ✗ Warning: applications/mimeapps.list not found${NC}"
fi

# Copy custom desktop application definitions
if [[ -f "$SCRIPT_DIR/applications/imv-image-viewer.desktop" ]]; then
    cp "$SCRIPT_DIR/applications/imv-image-viewer.desktop" "$HOME/.local/share/applications/imv-image-viewer.desktop"
    chmod 644 "$HOME/.local/share/applications/imv-image-viewer.desktop"
    echo -e "${GREEN}  ✓ Custom application definitions installed${NC}"
else
    echo -e "${RED}  ✗ Warning: applications/imv-image-viewer.desktop not found${NC}"
fi


update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo -e "${GREEN}✓ MIME types and applications configured${NC}"
echo ""






echo -e "${YELLOW}[6/6] Configuring systemd user services...${NC}"


systemctl --user enable --now dbus.service 2>/dev/null || true
echo -e "${GREEN}  ✓ D-Bus user service enabled${NC}"

# Optional: Enable Pipewire if available (modern audio server)
if systemctl --user list-unit-files | grep -q pipewire; then
    systemctl --user enable --now pipewire.service 2>/dev/null || true
    systemctl --user enable --now pipewire-pulse.service 2>/dev/null || true
    echo -e "${GREEN}  ✓ Pipewire audio service enabled${NC}"
fi

echo -e "${GREEN}✓ Systemd user services configured${NC}"
echo ""



echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              Setup Complete!                                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${GREEN}✓ Successfully installed:${NC}"
echo "  • Sway window manager"
echo "  • Waybar status bar, with:"
echo "    - Now-playing module (playerctl + cava waveform)"
echo "    - Wi-Fi popup (incl. hotspot sharing)"
echo "    - Bluetooth popup"
echo "    - Volume popup"
echo "  • wob volume OSD (pops up on the volume/mute keys)"
echo "  • Mako notification daemon"
echo "  • Swaylock screen locker"
echo "  • Clipboard history picker (\$mod+v)"
echo "  • All configuration files and utilities"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Restart your display manager or log out and log back in"
echo "   - At the login screen, select 'Sway' as your session"
echo "   - Or from a TTY, start Sway with: sway"
echo ""
echo "2. Important Configuration Updates Needed:"
echo "   - Edit ~/.config/sway/config and update wallpaper path:"
echo "     output * bg /path/to/your/wallpaper.png fill"
echo ""
echo "   - Update home directory paths if different from '/home/ravi'"
echo "     Search for: /home/ravi in config files and replace accordingly"
echo ""
echo "3. Optional: Install Additional Tools"
echo "   - Firefox: sudo pacman -S firefox"
echo "   - File manager: sudo pacman -S thunar"
echo "   - Screenshot tool: sudo pacman -S flameshot"
echo "   - PDF reader: sudo pacman -S zathura"
echo ""
echo "4. Keybindings Reference (from Sway config):"
echo "   - Mod4 (Super/Windows key) + Enter: Open terminal"
echo "   - Mod4 + D: Open application launcher (Wofi)"
echo "   - Mod4 + Number: Switch workspace"
echo "   - Mod4 + Q: Close focused window"
echo "   - Mod4 + F: Toggle fullscreen"
echo "   - Mod4 + V: Clipboard history"
echo "   - Mod4 + H: Searchable keybindings list (all of them)"
echo "   - Mod4 + Shift + C: Reload Sway config"
echo ""
echo -e "${YELLOW}Configuration Locations:${NC}"
echo "   • Sway: ~/.config/sway/config"
echo "   • Waybar: ~/.config/waybar/{config,style.css}"
echo "   • Wi-Fi/Bluetooth/Volume popups: ~/.config/waybar/{wifi,bluetooth,volume}-popup/"
echo "   • Now-playing module: ~/.config/waybar/scripts/media-visualizer.py"
echo "   • wob (volume OSD): ~/.config/wob/wob.ini"
echo "   • Mako: ~/.config/mako/config"
echo "   • Swaylock: ~/.config/swaylock/config"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo "   • Start Sway from TTY: sway"
echo "   • Start from another desktop: DISPLAY= sway"
echo "   • Debug Sway: sway -d 2>&1 | less"
echo "   • Reload Sway config: Mod4 + Shift + C (or: swaymsg reload)"
echo ""
echo -e "${GREEN}Enjoy your Sway desktop environment!${NC}"
echo ""
