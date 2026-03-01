import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

// Frames preview tab — grid view of extracted frame images
Item {
    id: root

    property var images: backend ? backend.frameImages : []

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

    // Header with frame count
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
                implicitWidth: 120

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
        anchors.margins: 8

        cellWidth: sizeSlider.value + 8
        cellHeight: sizeSlider.value + 28  // extra for filename label
        clip: true
        visible: images && images.length > 0

        model: images ? images.length : 0

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            Rectangle {
                anchors.fill: parent
                anchors.margins: 4
                radius: Theme.radiusMd
                color: delegateMa.containsMouse ? Theme.surfaceHover : Theme.surface
                border.color: Theme.borderSubtle
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 2

                    // Thumbnail
                    Image {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        source: images[index]
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        cache: true
                        smooth: true

                        // Loading placeholder
                        Rectangle {
                            anchors.fill: parent
                            color: Theme.border
                            visible: parent.status !== Image.Ready
                            radius: Theme.radiusSm

                            Icon {
                                anchors.centerIn: parent
                                name: "loader"
                                size: 20
                                color: Theme.textMuted
                                visible: parent.visible

                                RotationAnimation on rotation {
                                    from: 0; to: 360
                                    duration: 1200
                                    loops: Animation.Infinite
                                    running: parent.visible
                                }
                            }
                        }
                    }

                    // Filename
                    Text {
                        Layout.fillWidth: true
                        text: {
                            var url = images[index];
                            var parts = url.split('/');
                            return parts[parts.length - 1];
                        }
                        color: Theme.textMuted
                        font.pixelSize: 10
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                    }
                }

                MouseArea {
                    id: delegateMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onDoubleClicked: {
                        // Open full-size image
                        Qt.openUrlExternally(images[index])
                    }
                }
            }
        }
    }
}
