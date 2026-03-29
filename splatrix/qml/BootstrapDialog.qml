import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Window

Window {
    id: root
    visible: true
    width: 520
    height: 460
    minimumWidth: 520
    minimumHeight: 460
    maximumWidth: 520
    maximumHeight: 460
    title: "Splatrix"
    color: Theme.bg
    flags: Qt.Dialog
    modality: Qt.ApplicationModal

    x: (Screen.width - width) / 2
    y: (Screen.height - height) / 2

    property var ctrl: bootstrapController ?? null

    property string viewState: {
        if (!ctrl) return "prompt"
        if (ctrl.isComplete) return "complete"
        if (ctrl.errorMessage !== "") return "error"
        if (ctrl.isRunning) return "installing"
        return "prompt"
    }

    onClosing: function(close) {
        if (ctrl) ctrl.quit()
        close.accepted = true
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bg

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 32
            spacing: 0

            // ── Header ────────────────────────────────────────────

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                Layout.alignment: Qt.AlignHCenter

                Image {
                    source: "icons/app-icon.svg"
                    sourceSize: Qt.size(48, 48)
                    Layout.alignment: Qt.AlignHCenter
                }

                Text {
                    text: root.viewState === "complete"
                        ? "Setup Complete" : "First-Time Setup"
                    color: Theme.text
                    font.pixelSize: 20
                    font.weight: Font.DemiBold
                    Layout.alignment: Qt.AlignHCenter
                }

                Text {
                    text: {
                        if (root.viewState === "complete")
                            return "You're all set."
                        if (ctrl && ctrl.hasPartialInstall)
                            return "A previous setup was interrupted.\nClick Resume to continue where it left off."
                        var size = ctrl ? ctrl.sizeEstimate : ""
                        return "Splatrix needs to download required components"
                             + (size ? " (" + size + ")." : ".")
                    }
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSm
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                    lineHeight: 1.4
                }
            }

            Item { height: 20 }

            // ── Steps list ────────────────────────────────────────

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radiusLg
                color: Theme.surface
                border.color: Theme.borderSubtle
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 0

                    Repeater {
                        model: ctrl ? ctrl.stepsModel : []

                        Rectangle {
                            Layout.fillWidth: true
                            height: 38
                            radius: Theme.radiusSm
                            color: {
                                if (modelData.status === "in_progress")
                                    return Qt.rgba(0.23, 0.51, 0.96, 0.06)
                                if (modelData.status === "failed")
                                    return Qt.rgba(0.94, 0.27, 0.27, 0.06)
                                return "transparent"
                            }

                            Behavior on color { ColorAnimation { duration: 250 } }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 10

                                Item {
                                    width: 18; height: 18
                                    Layout.alignment: Qt.AlignVCenter

                                    Icon {
                                        anchors.centerIn: parent
                                        name: "circle"
                                        size: 16
                                        color: Theme.textMuted
                                        visible: modelData.status === "pending"
                                        opacity: 0.4
                                    }

                                    Icon {
                                        anchors.centerIn: parent
                                        name: "loader"
                                        size: 14
                                        color: Theme.running
                                        visible: modelData.status === "in_progress"

                                        RotationAnimation on rotation {
                                            from: 0; to: 360
                                            duration: 1200
                                            loops: Animation.Infinite
                                            running: modelData.status === "in_progress"
                                        }
                                    }

                                    Icon {
                                        anchors.centerIn: parent
                                        name: "check"
                                        size: 18
                                        color: Theme.accent
                                        visible: modelData.status === "completed"
                                    }

                                    Icon {
                                        anchors.centerIn: parent
                                        name: "x"
                                        size: 18
                                        color: Theme.error
                                        visible: modelData.status === "failed"
                                    }
                                }

                                Text {
                                    text: modelData.label
                                    color: {
                                        if (modelData.status === "completed")
                                            return Theme.accent
                                        if (modelData.status === "in_progress")
                                            return Theme.text
                                        if (modelData.status === "failed")
                                            return Theme.error
                                        return Theme.textMuted
                                    }
                                    font.pixelSize: Theme.fontSizeSm
                                    font.weight: modelData.status === "in_progress"
                                        ? Font.Medium : Font.Normal
                                    Layout.fillWidth: true

                                    Behavior on color { ColorAnimation { duration: 200 } }
                                }
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }
                }
            }

            Item { height: 12 }

            // ── Error banner ──────────────────────────────────────

            Rectangle {
                Layout.fillWidth: true
                visible: ctrl ? ctrl.errorMessage !== "" : false
                implicitHeight: errorText.implicitHeight + 20
                radius: Theme.radiusSm
                color: Qt.rgba(0.94, 0.27, 0.27, 0.08)
                border.color: Qt.rgba(0.94, 0.27, 0.27, 0.25)
                border.width: 1

                Text {
                    id: errorText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: ctrl ? ctrl.errorMessage : ""
                    color: Theme.error
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                }
            }

            Item { height: 16 }

            // ── Buttons ───────────────────────────────────────────

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Layout.alignment: Qt.AlignRight

                Rectangle {
                    visible: root.viewState !== "complete"
                    width: 72
                    height: 36
                    radius: Theme.radiusMd
                    color: _quitMa.containsMouse ? Theme.surfaceHover : "transparent"
                    border.color: Theme.border
                    border.width: 1

                    Text {
                        anchors.centerIn: parent
                        text: "Quit"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeSm
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        id: _quitMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { if (ctrl) ctrl.quit() }
                    }

                    Behavior on color { ColorAnimation { duration: 150 } }
                }

                Rectangle {
                    width: 110
                    height: 36
                    radius: Theme.radiusMd
                    color: {
                        if (root.viewState === "installing")
                            return Qt.darker(Theme.accent, 1.4)
                        return _primaryMa.containsMouse
                            ? Theme.accentHover : Theme.accent
                    }
                    opacity: root.viewState === "installing" ? 0.7 : 1.0

                    Text {
                        id: _primaryText
                        anchors.centerIn: parent
                        text: {
                            if (root.viewState === "complete")
                                return "Continue"
                            if (root.viewState === "error")
                                return "Retry"
                            if (root.viewState === "installing")
                                return "Installing..."
                            return (ctrl && ctrl.hasPartialInstall)
                                ? "Resume" : "Install"
                        }
                        color: "#ffffff"
                        font.pixelSize: Theme.fontSizeSm
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        id: _primaryMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: root.viewState === "installing"
                            ? Qt.ArrowCursor : Qt.PointingHandCursor
                        enabled: root.viewState !== "installing"
                        onClicked: {
                            if (!ctrl) return
                            if (root.viewState === "complete")
                                ctrl.proceed()
                            else
                                ctrl.startInstall()
                        }
                    }

                    Behavior on color { ColorAnimation { duration: 150 } }
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                }
            }
        }
    }
}
