import QtQuick
import QtQuick.Layouts
import QtWebEngine

// 3D Viewer tab — embeds viewer.html via WebEngineView
Item {
    id: root

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    WebEngineView {
        id: webView
        anchors.fill: parent
        url: backend ? backend.viewerUrl : "about:blank"
        backgroundColor: Theme.bg

        settings.localContentCanAccessFileUrls: true
        settings.localContentCanAccessRemoteUrls: true

        onLoadingChanged: function(loadRequest) {
            if (loadRequest.status === WebEngineView.LoadFailedStatus)
                console.warn("Viewer load failed:", loadRequest.errorString)
        }
    }

    // Reload viewer when URL changes
    Connections {
        target: backend
        function onViewerUrlChanged() {
            webView.url = backend.viewerUrl
        }
    }
}
