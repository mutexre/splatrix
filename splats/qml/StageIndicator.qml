import QtQuick
import QtQuick.Layouts

// Pipeline stage row — matches web StageIndicator component
Rectangle {
    id: root

    // ── Model properties ──
    property string label: "Stage"
    property string stageKey: ""
    property string status: "pending"    // pending | running | completed | failed | cancelled
    property real   progress: 0.0        // 0..1
    property string detail: ""

    property bool canPlay: false    // controlled by parent
    signal openFolderClicked(string key)
    signal playClicked(string key)

    Layout.fillWidth: true
    implicitHeight: col.implicitHeight + 20
    radius: Theme.radiusMd
    border.color: Theme.borderSubtle
    border.width: 1
    color: _bgColor()

    Behavior on color { ColorAnimation { duration: 250 } }

    ColumnLayout {
        id: col
        anchors {
            fill: parent
            leftMargin: 12
            rightMargin: 12
            topMargin: 10
            bottomMargin: 10
        }
        spacing: 6

        RowLayout {
            spacing: 10
            Layout.fillWidth: true

            // Status icon (using Lucide SVG icons)
            Item {
                width: 20; height: 20
                Layout.alignment: Qt.AlignVCenter

                // Pending — circle icon (muted)
                Icon {
                    anchors.centerIn: parent
                    name: "circle"
                    size: 18
                    color: Theme.textMuted
                    visible: root.status === "pending"
                }

                // Running — loader icon (spinning)
                Icon {
                    id: loaderIcon
                    anchors.centerIn: parent
                    name: "loader"
                    size: 15
                    color: Theme.running
                    visible: root.status === "running"

                    RotationAnimation on rotation {
                        from: 0; to: 360
                        duration: 1200
                        loops: Animation.Infinite
                        running: root.status === "running"
                    }
                }

                // Completed — check icon
                Icon {
                    anchors.centerIn: parent
                    name: "check"
                    size: 20
                    color: Theme.success
                    visible: root.status === "completed"
                }

                // Failed — x icon
                Icon {
                    anchors.centerIn: parent
                    name: "x"
                    size: 20
                    color: Theme.error
                    visible: root.status === "failed"
                }

                // Cancelled — ban icon
                Icon {
                    anchors.centerIn: parent
                    name: "ban"
                    size: 18
                    color: Theme.warning
                    visible: root.status === "cancelled"
                }
            }

            // Stage label
            Text {
                text: root.label
                color: Theme.text
                font.pixelSize: Theme.fontSizeSm
                font.weight: Font.Medium
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            // Detail text (hidden when completed — icon is enough)
            Text {
                text: root.detail || root.status
                color: _statusColor()
                font.pixelSize: Theme.fontSizeXs
                visible: root.status !== "completed"
            }

            // Play button (start from this stage)
            Rectangle {
                width: 24; height: 24
                radius: Theme.radiusSm
                color: playMa.containsMouse ? Theme.surfaceHover : "transparent"
                visible: root.canPlay && root.status !== "running"
                opacity: root.canPlay ? 1.0 : 0.3
                Layout.alignment: Qt.AlignVCenter

                Icon {
                    anchors.centerIn: parent
                    name: "play"
                    size: 14
                    color: Theme.accent
                }

                MouseArea {
                    id: playMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.playClicked(root.stageKey)
                }
            }

            // Open folder button (completed stages only)
            Rectangle {
                width: 24; height: 24
                radius: Theme.radiusSm
                color: folderMa.containsMouse ? Theme.surfaceHover : "transparent"
                visible: root.status === "completed" && root.stageKey !== ""
                Layout.alignment: Qt.AlignVCenter

                Icon {
                    anchors.centerIn: parent
                    name: "folder-open"
                    size: 16
                    color: Theme.textMuted
                }

                MouseArea {
                    id: folderMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.openFolderClicked(root.stageKey)
                }
            }
        }

        // Progress bar (only when running)
        Item {
            Layout.fillWidth: true
            height: 4
            visible: root.status === "running"

            Rectangle {
                anchors.fill: parent
                radius: 2
                color: Theme.border
            }

            Rectangle {
                width: parent.width * Math.min(root.progress, 1.0)
                height: parent.height
                radius: 2
                color: Theme.accent

                Behavior on width {
                    NumberAnimation { duration: 400; easing.type: Easing.OutCubic }
                }
            }
        }
    }

    function _bgColor() {
        switch (status) {
            case "running":   return Qt.rgba(0.23, 0.51, 0.96, 0.06)
            case "completed": return Qt.rgba(0.13, 0.77, 0.37, 0.06)
            case "failed":    return Qt.rgba(0.94, 0.27, 0.27, 0.06)
            case "cancelled": return Qt.rgba(0.92, 0.70, 0.03, 0.06)
            default:          return "transparent"
        }
    }

    function _statusColor() {
        switch (status) {
            case "running":   return Theme.running
            case "completed": return Theme.success
            case "failed":    return Theme.error
            case "cancelled": return Theme.warning
            default:          return Theme.textMuted
        }
    }
}
