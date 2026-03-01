import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

// Pipeline editor tab — scrollable content + pinned bottom buttons
Item {
    id: root

    // ── Scrollable content ──────────────────────────────────────
    Flickable {
        id: flick
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
            bottom: buttonBar.top
        }
        contentHeight: mainCol.implicitHeight + 32
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

        ColumnLayout {
            id: mainCol
            anchors {
                left: parent.left; right: parent.right
                top: parent.top
                margins: Theme.spacingLg
            }
            spacing: Theme.spacingLg

            // ── Settings ─────────────────────────────────────────
            SectionCard {
                title: "Settings"
                iconName: "settings"

                // Video input row
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacing

                    Text {
                        text: "Video"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeXs
                        font.weight: Font.Medium
                        Layout.alignment: Qt.AlignVCenter
                    }

                    IconButton {
                        text: "Select"
                        iconName: "folder-open"
                        enabled: backend ? !backend.isProcessing : true
                        onClicked: backend.selectVideo()
                    }

                    Text {
                        text: backend ? (backend.videoName || "No video selected") : "No video selected"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeSm
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                    }
                }

                // Separator
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Theme.borderSubtle
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: Theme.spacingLg
                    rowSpacing: Theme.spacing

                    // Max Frames
                    ColumnLayout {
                        spacing: 4
                        Text {
                            text: "Max Frames"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontSizeXs
                        }
                        SpinBox {
                            id: maxFramesSpin
                            from: 0; to: 10000; stepSize: 10
                            editable: true
                            value: backend ? backend.maxFrames : 300
                            enabled: backend ? !backend.isProcessing : true
                            Layout.fillWidth: true
                            onValueModified: if (backend) backend.maxFrames = value

                            contentItem: TextInput {
                                text: maxFramesSpin.value === 0 ? "Unlimited" : maxFramesSpin.textFromValue(maxFramesSpin.value, maxFramesSpin.locale)
                                color: Theme.text
                                selectionColor: Theme.accent
                                selectedTextColor: "#fff"
                                horizontalAlignment: Qt.AlignHCenter
                                verticalAlignment: Qt.AlignVCenter
                                readOnly: !maxFramesSpin.editable
                                validator: maxFramesSpin.validator
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                font.pixelSize: Theme.fontSizeSm
                            }

                            background: Rectangle {
                                implicitWidth: 120; implicitHeight: 32
                                color: Theme.bg
                                border.color: maxFramesSpin.activeFocus ? Theme.accent : Theme.borderSubtle
                                border.width: 1
                                radius: Theme.radiusMd
                            }

                            up.indicator: Rectangle {
                                x: parent.width - width; width: 24; height: parent.height
                                color: "transparent"
                                Text { text: "+"; color: Theme.textMuted; font.pixelSize: 14; anchors.centerIn: parent }
                            }
                            down.indicator: Rectangle {
                                x: 0; width: 24; height: parent.height
                                color: "transparent"
                                Text { text: "−"; color: Theme.textMuted; font.pixelSize: 14; anchors.centerIn: parent }
                            }
                        }
                    }

                    // Training Iterations
                    ColumnLayout {
                        spacing: 4
                        Text {
                            text: "Training Iterations"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontSizeXs
                        }
                        SpinBox {
                            id: iterSpin
                            from: 1000; to: 100000; stepSize: 5000
                            editable: true
                            value: backend ? backend.trainingIterations : 30000
                            enabled: backend ? !backend.isProcessing : true
                            Layout.fillWidth: true
                            onValueModified: if (backend) backend.trainingIterations = value

                            contentItem: TextInput {
                                text: iterSpin.textFromValue(iterSpin.value, iterSpin.locale)
                                color: Theme.text
                                selectionColor: Theme.accent
                                selectedTextColor: "#fff"
                                horizontalAlignment: Qt.AlignHCenter
                                verticalAlignment: Qt.AlignVCenter
                                readOnly: !iterSpin.editable
                                validator: iterSpin.validator
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                font.pixelSize: Theme.fontSizeSm
                            }

                            background: Rectangle {
                                implicitWidth: 120; implicitHeight: 32
                                color: Theme.bg
                                border.color: iterSpin.activeFocus ? Theme.accent : Theme.borderSubtle
                                border.width: 1
                                radius: Theme.radiusMd
                            }

                            up.indicator: Rectangle {
                                x: parent.width - width; width: 24; height: parent.height
                                color: "transparent"
                                Text { text: "+"; color: Theme.textMuted; font.pixelSize: 14; anchors.centerIn: parent }
                            }
                            down.indicator: Rectangle {
                                x: 0; width: 24; height: parent.height
                                color: "transparent"
                                Text { text: "−"; color: Theme.textMuted; font.pixelSize: 14; anchors.centerIn: parent }
                            }
                        }
                    }
                }
            }

            // ── Pipeline Progress ───────────────────────────────────
            SectionCard {
                title: "Pipeline Progress"

                // Stage indicators — fixed count to avoid Repeater rebuild flicker
                Repeater {
                    model: 6

                    StageIndicator {
                        required property int index
                        readonly property var s: (backend && backend.stages.length > index) ? backend.stages[index] : null
                        Layout.fillWidth: true
                        stageKey: s ? s.key : ""
                        label: s ? s.label : ""
                        status: s ? s.status : "pending"
                        progress: s ? s.progress : 0.0
                        detail: s ? s.detail : ""
                        onOpenFolderClicked: function(key) {
                            if (backend) backend.openStageFolder(key)
                        }
                    }
                }
            }
        }
    }

    // ── Pinned bottom button bar ────────────────────────────────
    Rectangle {
        id: buttonBar
        anchors {
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        height: buttonRow.implicitHeight + Theme.spacingLg * 2
        color: Theme.bg

        // Top border
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 1
            color: Theme.borderSubtle
        }

        Row {
            id: buttonRow
            anchors {
                left: parent.left
                verticalCenter: parent.verticalCenter
                leftMargin: Theme.spacingLg
            }
            spacing: Theme.spacing

            IconButton {
                text: "Start Conversion"
                variant: "primary"
                iconName: "play"
                enabled: backend ? (backend.hasVideo && !backend.isProcessing) : false
                onClicked: backend.startConversion()
            }

            IconButton {
                text: "Export PLY"
                iconName: "rotate-ccw"
                enabled: backend ? (backend.canResumeTraining && !backend.isProcessing) : false
                onClicked: backend.resumeFromTraining()
            }

            IconButton {
                text: "Cancel"
                variant: "danger"
                iconName: "square"
                enabled: backend ? backend.isProcessing : false
                onClicked: backend.cancel()
            }
        }
    }
}
