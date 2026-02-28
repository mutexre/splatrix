import QtQuick
import QtQuick.Layouts

// Card container matching the web "Section" component
Rectangle {
    id: root

    property string title: ""
    property string iconName: ""   // Lucide icon name
    default property alias content: contentColumn.data

    color: Theme.surface
    border.color: Theme.borderSubtle
    border.width: 1
    radius: Theme.radiusLg

    implicitHeight: col.implicitHeight + 2 * Theme.spacingLg
    Layout.fillWidth: true

    ColumnLayout {
        id: col
        anchors {
            fill: parent
            margins: Theme.spacingLg
        }
        spacing: 12

        // Header
        RowLayout {
            spacing: 6
            visible: root.title !== ""

            Icon {
                name: root.iconName
                size: 16
                color: Theme.textMuted
                visible: root.iconName !== ""
            }
            Text {
                text: root.title.toUpperCase()
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeXs
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
            }
        }

        // Content slot
        ColumnLayout {
            id: contentColumn
            Layout.fillWidth: true
            spacing: Theme.spacing
        }
    }
}
