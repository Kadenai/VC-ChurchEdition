"""Small inline SVG icon set for the WebUI.

The icons are Lucide-style strokes using currentColor so they inherit the local
text color and work in both light and dark mode without external assets.
"""

ICONS = {
    "alert-triangle": '<path d="m21.7 18.9-8.5-15a1.4 1.4 0 0 0-2.4 0l-8.5 15A1.4 1.4 0 0 0 3.5 21h17a1.4 1.4 0 0 0 1.2-2.1Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "broom": '<path d="M3 21h12"/><path d="M5 21v-4.5L14.5 7"/><path d="m14 7 3-3 3 3-3 3z"/><path d="M8 16h7l-2 5H6z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "circle-x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "droplet": '<path d="M12 22a7 7 0 0 0 7-7c0-4-7-13-7-13S5 11 5 15a7 7 0 0 0 7 7Z"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "file-up": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M12 12v6"/><path d="m9 15 3-3 3 3"/>',
    "film": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M3 8h4"/><path d="M17 8h4"/><path d="M3 16h4"/><path d="M17 16h4"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15 8 3 3"/><path d="m17 6 3 3"/>',
    "lightbulb": '<path d="M15 14c.2-1.1.8-1.8 1.5-2.7A6 6 0 1 0 7.5 11.3c.7.9 1.3 1.6 1.5 2.7"/><path d="M9 18h6"/><path d="M10 22h4"/>',
    "message-circle": '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 1 1 17 0Z"/>',
    "moon": '<path d="M12 3a6.4 6.4 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "palette": '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 22a10 10 0 1 1 10-10c0 3-2 4-4 4h-1.5a2.5 2.5 0 0 0 0 5H12Z"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "refresh": '<path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"/><path d="M3 21v-5h5"/><path d="M3 12A9 9 0 0 1 18.4 5.6L21 8"/><path d="M21 3v5h-5"/>',
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9"/><path d="M14.5 14.5 20 20"/><path d="M8.1 8.1 12 12"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "sparkles": '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.9 4.9 1.4 1.4"/><path d="m17.7 17.7 1.4 1.4"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.3 17.7-1.4 1.4"/><path d="m19.1 4.9-1.4 1.4"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8 12 3 7 8"/><path d="M12 3v12"/>',
    "volume-2": '<path d="M11 5 6 9H2v6h4l5 4Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
    "wand": '<path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9H6"/><path d="M20 9h-2"/><path d="m17.8 6.2 1.4-1.4"/><path d="m10.8 13.2-1.4 1.4"/><path d="m10.8 4.8-1.4-1.4"/><path d="m17.8 11.8 1.4 1.4"/><path d="m3 21 9-9"/>',
    "zap": '<path d="M13 2 3 14h9l-1 8 10-12h-9Z"/>',
}


def icon(name, size=18, class_name="vc-icon", stroke_width=2):
    """Return an inline SVG by name, or an empty string if the icon is unknown."""
    paths = ICONS.get(name)
    if not paths:
        return ""
    return (
        f'<svg class="{class_name}" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{paths}</svg>'
    )

