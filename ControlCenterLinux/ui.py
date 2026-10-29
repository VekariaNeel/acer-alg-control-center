"""Native GTK presentation helpers. Previews never send hardware commands."""
import html
import math
import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk


COLOR_PRESETS = (
    ("Red", "#FF0000"), ("Orange", "#FF8000"), ("Amber", "#FFBF00"),
    ("Yellow", "#FFFF00"), ("Lime", "#80FF00"), ("Green", "#00FF00"),
    ("Sea green", "#00FF80"), ("Cyan", "#00FFFF"), ("Sky", "#0080FF"),
    ("Blue", "#0000FF"), ("Purple", "#8000FF"), ("Magenta", "#FF00FF"),
    ("Coral", "#FF8C8C"), ("Apricot", "#FFC58C"), ("Soft amber", "#FFCA75"),
    ("Lemon", "#FFFF8C"), ("Soft lime", "#C5FF8C"), ("Soft green", "#8CFF8C"),
    ("Mint", "#64DFC4"), ("Aqua", "#8CFFFF"), ("Ice", "#66BFFF"),
    ("Periwinkle", "#8C8CFF"), ("Violet", "#B39AFF"), ("Rose", "#FF91B2"),
    ("White", "#FFFFFF"), ("Ivory", "#FFFFE0"), ("Warm white", "#FFE4BD"),
    ("Peach", "#FFDAB9"), ("Blush", "#FFE4E8"), ("Lavender", "#E6D8FF"),
    ("Cool white", "#E2F3FF"), ("Pale mint", "#D5FFF1"), ("Silver", "#C0C0C0"),
    ("Slate", "#708090"), ("Charcoal", "#303848"), ("Black", "#000000"),
)


def color_swatch(color):
    picture = Gtk.Picture(can_shrink=True)
    picture.set_size_request(18, 22)
    render_svg(picture, f'<svg xmlns="http://www.w3.org/2000/svg" width="38" height="22"><rect width="38" height="22" rx="4" fill="{color}"/></svg>')
    return picture


def render_svg(picture, markup):
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(markup.encode("utf-8"))
    loader.close()
    picture.set_pixbuf(loader.get_pixbuf())


def keyboard_preview():
    picture = Gtk.Picture(can_shrink=True, keep_aspect_ratio=True)
    picture.set_size_request(-1, 165)
    picture.color = [80, 210, 190]
    picture.level = 3

    def refresh():
        strength = max(0, min(4, picture.level)) / 4
        color = [max(0, min(255, channel)) / 255 for channel in picture.color]
        stroke = "#" + "".join(f"{round((0.21 + channel * strength * 0.65) * 255):02x}" for channel in color)
        fill = "#" + "".join(f"{round((0.08 + channel * strength * 0.12) * 255):02x}" for channel in color)
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="740" height="190" viewBox="0 0 740 190">',
                 '<rect x="3" y="5" width="734" height="178" rx="14" fill="#0c1117" stroke="#3b4a5e"/>']
        legends = [list("1234567890-="), list("QWERTYUIOP[]"), list("ASDFGHJKL;\'"), list("ZXCVBNM,./")]
        for row, keys in enumerate(legends):
            offset = (0, 9, 18, 30)[row]
            for column, legend in enumerate(keys):
                x, y = 22 + offset + column * 48, 20 + row * 31
                parts.append(f'<rect x="{x}" y="{y}" width="41" height="25" rx="4" fill="{fill}" stroke="{stroke}"/>')
                parts.append(f'<text x="{x + 7}" y="{y + 16}" fill="{stroke}" font-size="9" font-family="sans-serif">{html.escape(legend)}</text>')
        for x, width in ((22, 62), (91, 55), (153, 285), (445, 55), (507, 55), (569, 55), (631, 82)):
            parts.append(f'<rect x="{x}" y="147" width="{width}" height="22" rx="4" fill="{fill}" stroke="{stroke}"/>')
        for row in range(4):
            for column in range(2):
                parts.append(f'<rect x="{627 + column * 44}" y="{20 + row * 31}" width="37" height="25" rx="4" fill="{fill}" stroke="{stroke}"/>')
        parts.append('</svg>')
        render_svg(picture, "".join(parts))

    picture.refresh = refresh
    picture.set_tooltip_text("Lighting preview only. Select Apply to change the physical keyboard.")
    refresh()
    return picture


def battery_preview():
    picture = Gtk.Picture(can_shrink=True, keep_aspect_ratio=True)
    picture.set_size_request(-1, 150)
    picture.capacity = None

    def refresh():
        capacity = None if picture.capacity is None else max(0, min(100, picture.capacity))
        circumference = 2 * math.pi * 58
        dash = 0 if capacity is None else circumference * capacity / 100
        text = "—" if capacity is None else f"{capacity:.0f}%"
        render_svg(picture, f'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150" viewBox="0 0 300 150">
          <circle cx="150" cy="75" r="58" fill="none" stroke="#293648" stroke-width="9"/>
          <circle cx="150" cy="75" r="58" fill="none" stroke="#9ae7d5" stroke-width="9"
            stroke-linecap="round" stroke-dasharray="{dash} {circumference}" transform="rotate(-90 150 75)"/>
          <text x="150" y="85" text-anchor="middle" fill="#edf5ff" font-family="sans-serif" font-size="30" font-weight="700">{text}</text>
        </svg>''')

    picture.refresh = refresh
    refresh()
    return picture
