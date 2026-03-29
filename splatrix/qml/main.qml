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
    title: backend ? backend.windowTitle : "Splatrix"
    color: Theme.bg

    onClosing: function(close) {
        if (backend) backend.windowClosing()
        close.accepted = true
    }

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
                TabButton2 { iconName: "grid";   label: "Frames";        tabIndex: 2 }
                TabButton2 { iconName: "box";    label: "3D Viewer";     tabIndex: 3 }
                TabButton2 { iconName: "list";   label: "Log";           tabIndex: 4 }
            }
        }
    }


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
            onSwitchToTab: function(idx) { tabStack.currentIndex = idx }
        }

        VideoTab {
            Layout.fillWidth: true
            Layout.fillHeight: true
            isActiveTab: tabStack.currentIndex === 1
        }

        FramesTab {
            Layout.fillWidth: true
            Layout.fillHeight: true
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

    component HeaderButton: Item {
        property string iconName: ""
        property string label: ""
        signal clicked()

        width: _row.implicitWidth + 16
        height: 30

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusMd
            color: Theme.surfaceHover
            opacity: _ma.containsMouse ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 120 } }
        }

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
                font.pixelSize: Theme.fontSizeSm
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
    }

    component TabButton2: Item {
        property string iconName: ""
        property string label: ""
        property int tabIndex: 0
        property bool isActive: tabStack.currentIndex === tabIndex

        width: _tabRow.implicitWidth + 20
        height: 30

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusMd
            color: isActive ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.15)
                            : Theme.surfaceHover
            opacity: isActive || _tabMa.containsMouse ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 120 } }
        }

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
    }
}
