import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

// Pipeline editor tab — settings, stages, controls
Flickable {
    id: root
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

        // ── Video Input ─────────────────────────────────────────
        SectionCard {
            title: "Video Input"
            iconName: "upload"

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacing

                IconButton {
                    text: "Select Video"
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
        }

        // ── Processing Options ──────────────────────────────────
        SectionCard {
            title: "Processing Options"
            iconName: "settings"

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

                // Method (spans 2 columns)
                ColumnLayout {
                    Layout.columnSpan: 2
                    spacing: 4

                    Text {
                        text: "Method"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeXs
                    }
                    ComboBox {
                        id: methodCombo
                        model: ["Mock (Fast, test only)", "Nerfstudio (GPU required)", "COLMAP (Requires install)"]
                        currentIndex: backend ? backend.reconstructionMethod : 1
                        enabled: backend ? !backend.isProcessing : true
                        Layout.fillWidth: true
                        onCurrentIndexChanged: if (backend) backend.reconstructionMethod = currentIndex

                        contentItem: Text {
                            leftPadding: 10
                            text: methodCombo.displayText
                            color: Theme.text
                            font.pixelSize: Theme.fontSizeSm
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }

                        background: Rectangle {
                            implicitHeight: 32
                            color: Theme.bg
                            border.color: methodCombo.activeFocus ? Theme.accent : Theme.borderSubtle
                            border.width: 1
                            radius: Theme.radiusMd
                        }

                        popup: Popup {
                            y: methodCombo.height + 2
                            width: methodCombo.width
                            implicitHeight: contentItem.implicitHeight + 4
                            padding: 2

                            contentItem: ListView {
                                clip: true
                                implicitHeight: contentHeight
                                model: methodCombo.popup.visible ? methodCombo.delegateModel : null
                                currentIndex: methodCombo.highlightedIndex
                            }

                            background: Rectangle {
                                color: Theme.surface
                                border.color: Theme.border
                                border.width: 1
                                radius: Theme.radiusMd
                            }
                        }

                        delegate: ItemDelegate {
                            width: methodCombo.width
                            contentItem: Text {
                                text: modelData
                                color: highlighted ? Theme.accent : Theme.text
                                font.pixelSize: Theme.fontSizeSm
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                color: highlighted ? Theme.surfaceHover : "transparent"
                                radius: Theme.radiusSm
                            }
                            highlighted: methodCombo.highlightedIndex === index
                        }
                    }
                }

                // Output PLY path (spans 2 columns)
                ColumnLayout {
                    Layout.columnSpan: 2
                    spacing: 4

                    Text {
                        text: "Output PLY"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeXs
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacing

                        TextField {
                            id: outputField
                            text: backend ? backend.outputPath : ""
                            enabled: backend ? !backend.isProcessing : true
                            Layout.fillWidth: true
                            onTextChanged: if (backend) backend.outputPath = text
                            color: Theme.text
                            font.pixelSize: Theme.fontSizeSm
                            placeholderText: "Output PLY path..."
                            placeholderTextColor: Theme.textMuted

                            background: Rectangle {
                                implicitHeight: 32
                                color: Theme.bg
                                border.color: outputField.activeFocus ? Theme.accent : Theme.borderSubtle
                                border.width: 1
                                radius: Theme.radiusMd
                            }
                        }

                        IconButton {
                            text: "Browse"
                            iconName: "folder"
                            enabled: backend ? !backend.isProcessing : true
                            onClicked: if (backend) backend.browseOutput()
                        }
                    }
                }
            }
        }

        // ── Pipeline Progress ───────────────────────────────────
        SectionCard {
            title: "Pipeline Progress"

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacing

                Text {
                    text: "Status:"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSm
                    font.weight: Font.DemiBold
                }
                Text {
                    text: backend ? backend.statusText : "Ready"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSm
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }

            // Stage indicators
            Repeater {
                model: backend ? backend.stages : []

                StageIndicator {
                    Layout.fillWidth: true
                    label: modelData.label
                    status: modelData.status
                    progress: modelData.progress
                    detail: modelData.detail
                }
            }
        }

        // ── Control Buttons ─────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            IconButton {
                text: "Start Conversion"
                variant: "primary"
                iconName: "play"
                enabled: backend ? (backend.hasVideo && !backend.isProcessing) : false
                Layout.fillWidth: true
                onClicked: backend.startConversion()
            }

            IconButton {
                text: "Re-export"
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

            IconButton {
                text: "Clear"
                iconName: "trash"
                enabled: backend ? !backend.isProcessing : true
                onClicked: backend.clear()
            }
        }
    }
}
