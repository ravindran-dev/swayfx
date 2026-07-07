"""Design tokens for the Wi-Fi popup. Single source of truth for ui.py and
the CSS is generated from these so colors never drift between the two."""
import os

POPUP_MIN_WIDTH = 320
POPUP_MAX_HEIGHT = 560
CORNER_RADIUS = 14
PADDING = 16
ROW_HEIGHT = 40
SEPARATOR = "rgba(255, 255, 255, 0.08)"
HOVER = "rgba(255, 255, 255, 0.05)"

# GTK's CSS engine has no backdrop-filter/blur - that's a browser-CSS-only
# property. Real background blur can only come from the compositor blurring
# what's behind this window's alpha channel (swayfx's "blur enable", already
# on) - the alpha here just has to be low enough for that to have something
# to blur. If swayfx isn't active, this alpha alone still reads fine as a
# plain translucent panel.
BG = "rgba(30, 30, 30, 0.82)"
BG_SOLID_FALLBACK = "#1e1e1e"

TEXT = "#e5e5e7"
TEXT_SECONDARY = "#a1a1a6"

# The user's own reference screenshot shows a coral/red accent switch and
# red "known network" indicator (a custom macOS accent color, not the
# stock blue) - matched here rather than assuming default Apple blue.
ACCENT = "#ff453a"
ACCENT_DIM = "rgba(255, 69, 58, 0.35)"

# Wi-Fi glyphs: reused verbatim from network-popup.sh's already-confirmed
# rendering (0xF05A9/0xF05AA), not retyped from memory - Nerd Font private-use
# codepoints are easy to get subtly wrong and silently render as tofu.
ICON_WIFI_ON = "\U000F05A9"    # 󰖩
ICON_WIFI_OFF = "\U000F05AA"   # 󰖪
# U+1F512 padlock renders as a yellow COLOR emoji in GTK (Noto Color Emoji
# wins the fallback) - wrong for a monochrome macOS-style list. U+F023 is
# the classic Font Awesome lock, bundled in every Nerd Font's PUA.
ICON_LOCK = ""           #
ICON_CHECK = "✓"          # ✓
ICON_CHEVRON = "›"        # ›

# Signal-bar glyphs: same 4 codepoints/thresholds as network-popup.sh,
# reused verbatim (verified in that file, not retyped).
def signal_icon(strength):
    if strength >= 80:
        return "\U000F0928"
    if strength >= 60:
        return "\U000F0925"
    if strength >= 40:
        return "\U000F0922"
    return "\U000F091F"

# SF Pro is Apple-licensed and can't be installed/redistributed on Linux.
# Inter is metrically close and fully open (SIL OFL) - staged as an
# optional `sudo pacman -S inter-font` install; falls back cleanly to
# Noto Sans (already installed) if that step hasn't been run yet.
FONT_STACK = "Inter, 'SF Pro Display', 'Noto Sans', sans-serif"

ANIM_DURATION_MS = 150
ANIM_SLIDE_PX = 8
ANIM_FPS = 60

STYLE_CSS_PATH = os.path.join(os.path.dirname(__file__), "styles.css")
