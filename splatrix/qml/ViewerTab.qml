import QtQuick
import QtQuick.Layouts

// 3D Viewer tab — loads WebEngine dynamically (only available after bootstrap)
Item {
    id: root

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    Loader {
        id: viewerLoader
        anchors.fill: parent
        active: backend ? backend.webEngineAvailable : false
        source: "ViewerWebEngine.qml"
    }

    // Placeholder when WebEngine is not yet installed
    Column {
        anchors.centerIn: parent
        spacing: 12
        visible: !viewerLoader.active

        Icon {
            name: "box"
            size: 48
            color: Theme.textMuted
            anchors.horizontalCenter: parent.horizontalCenter
        }

        Text {
            text: "3D Viewer"
            color: Theme.text
            font.pixelSize: 18
            font.weight: Font.DemiBold
            anchors.horizontalCenter: parent.horizontalCenter
        }

        Text {
            text: "Complete the initial setup to enable the 3D viewer."
            color: Theme.textMuted
            font.pixelSize: 13
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }
}
