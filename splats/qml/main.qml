import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Window

ApplicationWindow {
    id: window
    visible: true
    width: 1024
    height: 720
    minimumWidth: 800
    minimumHeight: 600
    title: backend ? backend.windowTitle : "Video to Gaussian Splats"
    color: Theme.bg

    // ── Header bar ──────────────────────────────────────────
    header: Rectangle {
        height: 44
        color: Theme.surface

        // Bottom border
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: Theme.borderSubtle
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 0

            // ── Project actions (left) ──
            Row {
                spacing: 2

                HeaderButton { iconName: "file-plus"; label: "New";  onClicked: backend.newProject() }
                HeaderButton { iconName: "folder-open"; label: "Open"; onClicked: backend.openProject() }
                HeaderButton { iconName: "save"; label: "Save"; onClicked: backend.saveProject() }
            }

            // Divider
            Rectangle {
                Layout.leftMargin: 10
                Layout.rightMargin: 10
                width: 1; height: 20; color: Theme.borderSubtle
                Layout.alignment: Qt.AlignVCenter
            }

            // ── Spacer — pushes tabs to the right ──
            Item { Layout.fillWidth: true }

            // ── Tabs (right-aligned) ──
            Row {
                spacing: 2

                TabButton2 { iconName: "layers"; label: "Pipeline";      tabIndex: 0 }
                TabButton2 { iconName: "video";  label: "Video Preview"; tabIndex: 1 }
                TabButton2 { iconName: "box";    label: "3D Viewer";     tabIndex: 2 }
                TabButton2 { iconName: "list";   label: "Log";           tabIndex: 3 }
            }

            // Divider
            Rectangle {
                Layout.leftMargin: 10
                Layout.rightMargin: 10
                width: 1; height: 20; color: Theme.borderSubtle
                Layout.alignment: Qt.AlignVCenter
            }

            // ── Project name + processing indicator ──
            Row {
                spacing: 6
                Layout.alignment: Qt.AlignVCenter

                Text {
                    text: backend ? backend.projectName : ""
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeXs
                    font.family: "monospace"
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, 180)
                    anchors.verticalCenter: parent.verticalCenter
                }

                // Pulsing dot
                Rectangle {
                    width: 6; height: 6; radius: 3
                    color: Theme.running
                    visible: backend ? backend.isProcessing : false
                    anchors.verticalCenter: parent.verticalCenter

                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: backend ? backend.isProcessing : false
                        NumberAnimation { to: 0.3; duration: 600 }
                        NumberAnimation { to: 1.0; duration: 600 }
                    }
                }

                Text {
                    text: "Processing"
                    color: Theme.running
                    font.pixelSize: Theme.fontSizeXs
                    visible: backend ? backend.isProcessing : false
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    // ── Tab content ─────────────────────────────────────────
    StackLayout {
        id: tabStack
        anchors.fill: parent

        onCurrentIndexChanged: {
            if (currentIndex !== 1 && backend)
                backend.pauseVideo()
        }

        PipelineTab {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        VideoTab {
            Layout.fillWidth: true
            Layout.fillHeight: true
            isActiveTab: tabStack.currentIndex === 1
        }

        ViewerTab {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        LogTab {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }

    // ── Inline components ───────────────────────────────────

    component HeaderButton: Rectangle {
        property string iconName: ""
        property string label: ""
        signal clicked()

        width: _row.implicitWidth + 16
        height: 30
        radius: Theme.radiusMd
        color: _ma.containsMouse ? Theme.surfaceHover : "transparent"

        Row {
            id: _row
            anchors.centerIn: parent
            spacing: 5

            Icon {
                name: iconName
                size: 15
                color: _ma.containsMouse ? Theme.text : Theme.textMuted
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: label
                color: _ma.containsMouse ? Theme.text : Theme.textMuted
                font.pixelSize: Theme.fontSizeXs
                font.weight: Font.Medium
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: _ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }

        Behavior on color { ColorAnimation { duration: 150 } }
    }

    component TabButton2: Rectangle {
        property string iconName: ""
        property string label: ""
        property int tabIndex: 0
        property bool isActive: tabStack.currentIndex === tabIndex

        width: _tabRow.implicitWidth + 20
        height: 30
        radius: Theme.radiusMd
        color: isActive ? Qt.rgba(0.39, 0.40, 0.95, 0.15)
             : _tabMa.containsMouse ? Theme.surfaceHover : "transparent"

        Row {
            id: _tabRow
            anchors.centerIn: parent
            spacing: 6

            Icon {
                name: iconName
                size: 16
                color: isActive ? Theme.accent : Theme.textMuted
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: label
                color: isActive ? Theme.accent : _tabMa.containsMouse ? Theme.text : Theme.textMuted
                font.pixelSize: Theme.fontSizeSm
                font.weight: Font.Medium
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: _tabMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tabStack.currentIndex = tabIndex
        }

        Behavior on color { ColorAnimation { duration: 150 } }
    }
}
