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

        onLoadingChanged: function(loadRequest) {
            if (loadRequest.status === WebEngineView.LoadFailedStatus)
                console.warn("Viewer load failed:", loadRequest.errorString)
        }
    }
}
