import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

// Frames preview tab — grid view of extracted frame images
Item {
    id: root

    property var images: backend ? backend.frameImages : []
    property int fitMode: 0  // 0=Fit, 1=Fill, 2=Stretch

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    // Empty state
    ColumnLayout {
        anchors.centerIn: parent
        spacing: 12
        visible: !images || images.length === 0

        Icon {
            name: "grid"
            size: 48
            color: Theme.textMuted
            Layout.alignment: Qt.AlignHCenter
            opacity: 0.4
        }

        Text {
            text: "No frames extracted yet"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSm
            Layout.alignment: Qt.AlignHCenter
        }

        Text {
            text: "Run the pipeline to extract frames from your video"
            color: Qt.rgba(Theme.textMuted.r, Theme.textMuted.g, Theme.textMuted.b, 0.6)
            font.pixelSize: Theme.fontSizeXs
            Layout.alignment: Qt.AlignHCenter
        }
    }

    // Header with frame count and controls
    Rectangle {
        id: headerBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 40
        color: Theme.surface
        visible: images && images.length > 0
        z: 1

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: Theme.borderSubtle
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 12

            Icon {
                name: "grid"
                size: 16
                color: Theme.textMuted
            }

            Text {
                text: images ? images.length + " frames" : "0 frames"
                color: Theme.text
                font.pixelSize: Theme.fontSizeSm
                font.weight: Font.Medium
            }

            Item { Layout.fillWidth: true }

            // Fit mode selector
            Row {
                spacing: 2

                Repeater {
                    model: ["Fit", "Fill", "Stretch"]
                    Rectangle {
                        width: label.implicitWidth + 16
                        height: 24
                        radius: Theme.radiusSm
                        color: root.fitMode === index
                               ? Qt.rgba(0.39, 0.40, 0.95, 0.15)
                               : fitMa.containsMouse ? Theme.surfaceHover : "transparent"

                        Text {
                            id: label
                            anchors.centerIn: parent
                            text: modelData
                            color: root.fitMode === index ? Theme.accent : Theme.textMuted
                            font.pixelSize: 11
                            font.weight: Font.Medium
                        }

                        MouseArea {
                            id: fitMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.fitMode = index
                        }
                    }
                }
            }

            // Separator
            Rectangle { width: 1; height: 20; color: Theme.borderSubtle }

            // Size slider
            Text {
                text: "Size"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeXs
            }

            Slider {
                id: sizeSlider
                from: 80; to: 320
                value: 160
                stepSize: 16
                implicitWidth: 100
                Layout.alignment: Qt.AlignVCenter

                background: Rectangle {
                    x: sizeSlider.leftPadding
                    y: sizeSlider.topPadding + sizeSlider.availableHeight / 2 - height / 2
                    width: sizeSlider.availableWidth
                    height: 3
                    radius: 2
                    color: Theme.border

                    Rectangle {
                        width: sizeSlider.visualPosition * parent.width
                        height: parent.height
                        radius: 2
                        color: Theme.accent
                    }
                }

                handle: Rectangle {
                    x: sizeSlider.leftPadding + sizeSlider.visualPosition * (sizeSlider.availableWidth - width)
                    y: sizeSlider.topPadding + sizeSlider.availableHeight / 2 - height / 2
                    width: 14; height: 14
                    radius: 7
                    color: sizeSlider.pressed ? Theme.accent : Theme.text
                    border.color: Theme.border
                    border.width: 1
                }
            }
        }
    }

    // Image grid
    GridView {
        id: grid
        anchors.top: headerBar.visible ? headerBar.bottom : parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 4

        property int thumbSize: sizeSlider.value

        cellWidth: thumbSize + 4
        cellHeight: thumbSize + 4
        clip: true
        visible: images && images.length > 0

        model: images ? images.length : 0

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Rectangle {
            width: grid.cellWidth
            height: grid.cellHeight
            color: "transparent"

            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                radius: Theme.radiusSm
                color: Theme.surface
                border.color: Theme.borderSubtle
                border.width: 1
                clip: true

                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: images[index]
                    fillMode: root.fitMode === 0 ? Image.PreserveAspectFit
                            : root.fitMode === 1 ? Image.PreserveAspectCrop
                            : Image.Stretch
                    asynchronous: true
                    cache: true
                    smooth: true
                    sourceSize.width: grid.thumbSize * 2
                    sourceSize.height: grid.thumbSize * 2
                }

                // Loading placeholder
                Rectangle {
                    anchors.fill: parent
                    color: Theme.border
                    visible: parent.children[0].status !== Image.Ready
                    radius: Theme.radiusSm
                    opacity: 0.5
                }
            }
        }
    }
}
