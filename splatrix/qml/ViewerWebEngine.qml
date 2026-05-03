import QtQuick
import QtWebEngine

// Actual WebEngineView — loaded dynamically by ViewerTab when WebEngine is available
Item {
    anchors.fill: parent

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

    Connections {
        target: backend
        function onViewerUrlChanged() {
            webView.url = backend.viewerUrl
        }
    }
}
