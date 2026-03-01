import QtQuick
import QtQuick.Effects

// Colorizable SVG icon component using MultiEffect
Item {
    id: root

    property string name: ""                // Icon filename without .svg
    property color color: Theme.textMuted   // Desired tint color
    property int size: 16

    width: size
    height: size

    Image {
        id: img
        source: root.name !== "" ? "icons/" + root.name + ".svg" : ""
        sourceSize: Qt.size(root.size, root.size)
        width: root.size
        height: root.size
        visible: false  // Hidden — MultiEffect renders it
        smooth: true
    }

    MultiEffect {
        anchors.fill: img
        source: img
        colorization: 1.0
        colorizationColor: root.color
    }
}
