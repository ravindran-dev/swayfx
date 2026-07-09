"""Design tokens for the Bluetooth popup - deliberately reuses the Wi-Fi
popup's styles.css verbatim (same window/row/switch classes, prefixed
"wifi-" in the CSS for historical reasons) so both popups are pixel-for-
pixel the same visual system, not two maintained in parallel."""
import os

POPUP_MIN_WIDTH = 320
POPUP_MAX_HEIGHT = 560

# Same 3 codepoints already confirmed rendering correctly in the waybar
# module itself (extracted and verified from the live config, not retyped).
ICON_BT_ON = "\U000F00AF"      # 󰂯 nf-md-bluetooth
ICON_BT_OFF = "\U000F00B2"     # 󰂲 nf-md-bluetooth_off
ICON_BT_CONNECTED = "\U000F00B1"  # 󰂱 nf-md-bluetooth_connect
ICON_CHECK = "✓"

FONT_STACK = "Inter, 'SF Pro Display', 'Noto Sans', sans-serif"

ANIM_DURATION_MS = 150
ANIM_SLIDE_PX = 8
ANIM_FPS = 60

STYLE_CSS_PATH = os.path.join(os.path.dirname(__file__), "styles.css")
