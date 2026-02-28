import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtMultimedia

// Video preview tab with player and controls
Item {
    id: root

    property bool isActiveTab: false

    onIsActiveTabChanged: {
        if (!isActiveTab && player.playbackState === MediaPlayer.PlayingState)
            player.pause()
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Video output area
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            VideoOutput {
                id: videoOutput
                anchors.fill: parent
            }

            // Overlay when no video
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                visible: !(backend && backend.hasVideo)

                Column {
                    anchors.centerIn: parent
                    spacing: 8

                    Icon {
                        name: "video"
                        size: 48
                        color: Theme.textMuted
                        anchors.horizontalCenter: parent.horizontalCenter
                        opacity: 0.4
                    }
                    Text {
                        text: "No video selected"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeLg
                        anchors.horizontalCenter: parent.horizontalCenter
                    }
                }
            }
        }

        // Controls bar
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 48
            color: Theme.surface

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 8

                // Play/Pause
                IconButton {
                    text: player.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                    iconName: player.playbackState === MediaPlayer.PlayingState ? "square" : "play"
                    implicitWidth: 90
                    onClicked: {
                        if (player.playbackState === MediaPlayer.PlayingState)
                            player.pause()
                        else if (player.source.toString() !== "")
                            player.play()
                    }
                }

                // Seek slider
                Slider {
                    id: seekSlider
                    Layout.fillWidth: true
                    from: 0
                    to: player.duration
                    value: player.position
                    onMoved: player.position = value

                    background: Rectangle {
                        x: seekSlider.leftPadding
                        y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                        width: seekSlider.availableWidth
                        height: 4
                        radius: 2
                        color: Theme.border

                        Rectangle {
                            width: seekSlider.visualPosition * parent.width
                            height: parent.height
                            radius: 2
                            color: Theme.accent
                        }
                    }

                    handle: Rectangle {
                        x: seekSlider.leftPadding + seekSlider.visualPosition * (seekSlider.availableWidth - width)
                        y: seekSlider.topPadding + seekSlider.availableHeight / 2 - height / 2
                        width: 14; height: 14; radius: 7
                        color: seekSlider.pressed ? Theme.accentHover : Theme.accent
                        border.color: Theme.bg
                        border.width: 2
                    }
                }

                // Time display
                Text {
                    text: _fmtMs(player.position) + " / " + _fmtMs(player.duration)
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeXs
                    font.family: "monospace"
                    Layout.preferredWidth: 100
                    horizontalAlignment: Text.AlignRight
                }
            }
        }

        // Video info bar
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: videoInfoText.implicitHeight + 8
            color: Qt.rgba(0, 0, 0, 0.6)
            visible: backend ? backend.videoInfo !== "" : false

            Text {
                id: videoInfoText
                anchors.centerIn: parent
                text: backend ? backend.videoInfo : ""
                color: "#aaa"
                font.pixelSize: Theme.fontSizeXs
            }
        }
    }

    MediaPlayer {
        id: player
        videoOutput: videoOutput
        audioOutput: AudioOutput {}
        source: backend ? backend.videoUrl : ""
    }

    function _fmtMs(ms) {
        var s = Math.floor(ms / 1000)
        var m = Math.floor(s / 60)
        s = s % 60
        return m + ":" + (s < 10 ? "0" : "") + s
    }
}
