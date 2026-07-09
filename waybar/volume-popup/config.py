"""Design tokens for the Volume popup - mirrors wifi-popup/config.py's
shape so ui.py, animations.py and styles.css are all drop-in compatible."""
import os

POPUP_MIN_WIDTH = 300
CORNER_RADIUS = 14

ANIM_DURATION_MS = 150
ANIM_SLIDE_PX = 8

# Extracted directly from waybar/config's own pulseaudio module (not
# retyped from memory - Nerd Font PUA codepoints are easy to get subtly
# wrong and silently render as tofu) so this popup's icons are pixel-
# identical to the waybar module that opens it.
ICON_MUTED = "\U000F075F"
ICON_LOW = "\U000F057F"
ICON_MEDIUM = "\U000F0580"
ICON_HIGH = "\U000F057E"


def volume_icon(pct, muted):
    if muted or pct == 0:
        return ICON_MUTED
    if pct < 34:
        return ICON_LOW
    if pct < 67:
        return ICON_MEDIUM
    return ICON_HIGH


# Reuses wifi-popup's stylesheet verbatim (same .wifi-popup/.wifi-popup-panel
# classes, same neon-cyan hairline) - one visual language across every
# waybar popup rather than a one-off for volume.
STYLE_CSS_PATH = os.path.join(os.path.dirname(__file__), "styles.css")
