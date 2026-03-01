import QtQuick
import QtQuick.Controls

// Styled button matching web btn-primary / btn-secondary / btn-danger
// Content is always horizontally centered
Button {
    id: root

    property string variant: "secondary"   // "primary" | "secondary" | "danger"
    property string iconName: ""           // Lucide icon filename (no .svg)

    hoverEnabled: true
    implicitHeight: 36
    leftPadding: 16
    rightPadding: 16

    contentItem: Row {
        spacing: 7
        // Center the row inside the button
        anchors.centerIn: parent

        Icon {
            name: root.iconName
            size: 16
            color: _textColor()
            visible: root.iconName !== ""
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.text
            color: _textColor()
            font.pixelSize: Theme.fontSizeSm
            font.weight: Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    background: Rectangle {
        implicitHeight: 36
        radius: Theme.radiusMd
        color: _bgColor()
        border.color: _borderColor()
        border.width: root.variant !== "primary" ? 1 : 0

        Behavior on color { ColorAnimation { duration: 150 } }
    }

    opacity: enabled ? 1.0 : 0.4

    function _bgColor() {
        if (!enabled) return Theme.surfaceHover
        if (variant === "primary")
            return root.hovered ? Theme.accentHover : Theme.accent
        if (variant === "danger")
            return root.hovered ? Qt.rgba(0.94, 0.27, 0.27, 0.2) : Qt.rgba(0.94, 0.27, 0.27, 0.1)
        return root.hovered ? Theme.surfaceHover : Theme.surface
    }

    function _borderColor() {
        if (variant === "primary") return "transparent"
        if (variant === "danger") return Qt.rgba(0.94, 0.27, 0.27, 0.2)
        return root.hovered ? Theme.border : Theme.borderSubtle
    }

    function _textColor() {
        if (variant === "primary") return "#ffffff"
        if (variant === "danger") return Theme.error
        return Theme.text
    }
}
