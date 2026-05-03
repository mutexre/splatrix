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
    color: t.bg
    flags: Qt.Dialog
    modality: Qt.ApplicationModal

    x: (Screen.width - width) / 2
    y: (Screen.height - height) / 2

    property var ctrl: bootstrapController ?? null
    property bool showingLog: false
    property bool hasActivity: viewState === "installing"
                               || viewState === "error"
                               || viewState === "complete"

    QtObject {
        id: t
        readonly property color bg: "#f8f8fc"
        readonly property color surface: "#ffffff"
        readonly property color surfaceHover: "#f0f0f5"
        readonly property color border: "#d4d4dc"
        readonly property color borderSubtle: "#e8e8f0"
        readonly property color text: "#1a1a2e"
        readonly property color textMuted: "#6b6b80"
        readonly property color accent: "#6366f1"
        readonly property color accentHover: "#818cf8"
        readonly property color error: "#ef4444"
        readonly property color running: "#3b82f6"
        readonly property int fontSizeSm: 14
        readonly property int radiusSm: 6
        readonly property int radiusMd: 8
        readonly property int radiusLg: 12
    }

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
        color: t.bg

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
                    color: t.text
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
                    color: t.textMuted
                    font.pixelSize: t.fontSizeSm
                    horizontalAlignment: Text.AlignHCenter
                    Layout.alignment: Qt.AlignHCenter
                    lineHeight: 1.4
                }
            }

            Item { height: 20 }

            // ── Content card ───────────────────────────────────────

            Rectangle {
                id: contentCard
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: t.radiusLg
                color: t.surface
                border.color: t.borderSubtle
                border.width: 1
                clip: true

                // ── Steps view ──────────────────────────────────

                Flickable {
                    id: stepsFlick
                    anchors.fill: parent
                    anchors.margins: 12
                    contentHeight: stepsColumn.height
                    boundsBehavior: Flickable.StopAtBounds
                    visible: !root.showingLog

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        contentItem: Rectangle {
                            implicitWidth: 4
                            radius: 2
                            color: t.textMuted
                            opacity: 0.4
                        }
                    }

                    Column {
                        id: stepsColumn
                        width: parent.width
                        spacing: 0

                        Repeater {
                            model: ctrl ? ctrl.stepsModel : []

                            Rectangle {
                                width: stepsColumn.width
                                height: 34
                                radius: t.radiusSm
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
                                            color: t.textMuted
                                            visible: modelData.status === "pending"
                                            opacity: 0.4
                                        }

                                        Icon {
                                            anchors.centerIn: parent
                                            name: "loader"
                                            size: 14
                                            color: t.running
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
                                            color: t.accent
                                            visible: modelData.status === "completed"
                                        }

                                        Icon {
                                            anchors.centerIn: parent
                                            name: "x"
                                            size: 18
                                            color: t.error
                                            visible: modelData.status === "failed"
                                        }
                                    }

                                    Text {
                                        text: modelData.label
                                        color: {
                                            if (modelData.status === "completed")
                                                return t.accent
                                            if (modelData.status === "in_progress")
                                                return t.text
                                            if (modelData.status === "failed")
                                                return t.error
                                            return t.textMuted
                                        }
                                        font.pixelSize: t.fontSizeSm
                                        font.weight: modelData.status === "in_progress"
                                            ? Font.Medium : Font.Normal
                                        Layout.fillWidth: true

                                        Behavior on color { ColorAnimation { duration: 200 } }
                                    }
                                }
                            }
                        }
                    }
                }

                // ── Log view ────────────────────────────────────

                Flickable {
                    id: logFlick
                    anchors.fill: parent
                    anchors.margins: 12
                    contentWidth: logContent.implicitWidth
                    contentHeight: logContent.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    visible: root.showingLog

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        contentItem: Rectangle {
                            implicitWidth: 4
                            radius: 2
                            color: t.textMuted
                            opacity: 0.4
                        }
                    }

                    ScrollBar.horizontal: ScrollBar {
                        policy: ScrollBar.AsNeeded
                        contentItem: Rectangle {
                            implicitHeight: 4
                            radius: 2
                            color: t.textMuted
                            opacity: 0.4
                        }
                    }

                    Text {
                        id: logContent
                        text: ctrl ? ctrl.logText : ""
                        color: t.textMuted
                        font.family: "Menlo"
                        font.pixelSize: 11
                        lineHeight: 1.35
                        textFormat: Text.PlainText

                        onTextChanged: {
                            if (root.showingLog)
                                logFlick.contentY = Math.max(0,
                                    logFlick.contentHeight - logFlick.height)
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: root.showingLog && (!ctrl || ctrl.logText === "")
                    text: "Waiting for output\u2026"
                    color: t.textMuted
                    font.pixelSize: 13
                    opacity: 0.5
                }
            }

            Item { height: 6 }

            // ── Error banner ──────────────────────────────────────

            Rectangle {
                Layout.fillWidth: true
                visible: ctrl ? ctrl.errorMessage !== "" : false
                implicitHeight: errorText.implicitHeight + 20
                radius: t.radiusSm
                color: Qt.rgba(0.94, 0.27, 0.27, 0.08)
                border.color: Qt.rgba(0.94, 0.27, 0.27, 0.25)
                border.width: 1

                Text {
                    id: errorText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: ctrl ? ctrl.errorMessage : ""
                    color: t.error
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                }
            }

            Item { height: 8 }

            // ── Buttons ───────────────────────────────────────────

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Rectangle {
                    width: 90
                    height: 36
                    radius: t.radiusMd
                    opacity: root.hasActivity ? 1.0 : 0.4
                    color: root.hasActivity && _logToggleMa.containsMouse
                           ? t.surfaceHover : "transparent"
                    border.color: t.borderSubtle
                    border.width: 1

                    Text {
                        id: _logLabel
                        anchors.centerIn: parent
                        text: root.showingLog ? "Hide Log" : "Show Log"
                        color: t.textMuted
                        font.pixelSize: t.fontSizeSm
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        id: _logToggleMa
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: root.hasActivity
                        cursorShape: root.hasActivity
                                     ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.showingLog = !root.showingLog
                    }

                    Behavior on color { ColorAnimation { duration: 150 } }
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    visible: root.viewState !== "complete"
                    width: 72
                    height: 36
                    radius: t.radiusMd
                    color: _quitMa.containsMouse ? t.surfaceHover : "transparent"
                    border.color: t.border
                    border.width: 1

                    Text {
                        anchors.centerIn: parent
                        text: "Quit"
                        color: t.textMuted
                        font.pixelSize: t.fontSizeSm
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
                    radius: t.radiusMd
                    color: {
                        if (root.viewState === "installing")
                            return Qt.darker(t.accent, 1.4)
                        return _primaryMa.containsMouse
                            ? t.accentHover : t.accent
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
                        font.pixelSize: t.fontSizeSm
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
