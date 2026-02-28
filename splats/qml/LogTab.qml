import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

// Log output tab
Item {
    id: root

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing
        spacing: Theme.spacing

        // Header
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            Icon {
                name: "list"
                size: 14
                color: Theme.textMuted
            }
            Text {
                text: "LOG"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeXs
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
            }

            Item { Layout.fillWidth: true }

            IconButton {
                text: "Clear"
                iconName: "trash"
                onClicked: if (backend) backend.clearLog()
            }
        }

        // Log area
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.surface
            radius: Theme.radiusMd
            border.color: Theme.borderSubtle
            border.width: 1

            Flickable {
                id: logFlick
                anchors.fill: parent
                anchors.margins: 12
                contentHeight: logText.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: Theme.border
                    }
                }

                Text {
                    id: logText
                    width: logFlick.width
                    text: backend ? backend.logContent : ""
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeXs
                    font.family: "monospace"
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    lineHeight: 1.4
                }

                // Auto-scroll to bottom
                onContentHeightChanged: {
                    if (contentHeight > height)
                        contentY = contentHeight - height
                }
            }
        }
    }
}
