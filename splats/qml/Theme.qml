pragma Singleton
import QtQuick

// Dark theme matching the web prototype
QtObject {
    // ── Background layers ──
    readonly property color bg:           "#0a0a0f"
    readonly property color surface:      "#12121a"
    readonly property color surfaceHover: "#1a1a25"

    // ── Borders ──
    readonly property color border:       "#2a2a3a"
    readonly property color borderSubtle: "#1e1e2e"

    // ── Text ──
    readonly property color text:         "#e4e4ef"
    readonly property color textMuted:    "#8888a0"

    // ── Accent ──
    readonly property color accent:       "#6366f1"
    readonly property color accentHover:  "#818cf8"

    // ── Semantic ──
    readonly property color success:  "#22c55e"
    readonly property color warning:  "#eab308"
    readonly property color error:    "#ef4444"
    readonly property color running:  "#3b82f6"

    // ── Typography ──
    readonly property string fontFamily: "Inter"
    readonly property int fontSizeXs:   12
    readonly property int fontSizeSm:   14
    readonly property int fontSizeMd:   15
    readonly property int fontSizeLg:   18

    // ── Geometry ──
    readonly property int radiusSm: 6
    readonly property int radiusMd: 8
    readonly property int radiusLg: 12
    readonly property int spacing:  8
    readonly property int spacingLg: 16
}
