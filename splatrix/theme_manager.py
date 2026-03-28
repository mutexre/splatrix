"""Theme manager — loads YAML theme files and exposes them to QML.

Detects macOS / system color scheme on startup and watches for changes,
automatically switching between 'dark' and 'light' themes.  The object
is set as a QML context property named ``Theme`` so existing QML code
(``Theme.bg``, ``Theme.accent``, …) works unchanged.
"""

import sys
from pathlib import Path

import yaml
from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtGui import QColor, QGuiApplication


_THEMES_DIR = Path(__file__).parent / "themes"

_DEFAULT_COLORS = {
    "bg": "#0a0a0f",
    "surface": "#12121a",
    "surfaceHover": "#1a1a25",
    "border": "#2a2a3a",
    "borderSubtle": "#1e1e2e",
    "text": "#e4e4ef",
    "textMuted": "#8888a0",
    "accent": "#6366f1",
    "accentHover": "#818cf8",
    "success": "#22c55e",
    "warning": "#eab308",
    "error": "#ef4444",
    "running": "#3b82f6",
}

_DEFAULT_TYPOGRAPHY = {
    "fontFamily": "Inter",
    "fontSizeXs": 12,
    "fontSizeSm": 14,
    "fontSizeMd": 15,
    "fontSizeLg": 18,
}

_DEFAULT_GEOMETRY = {
    "radiusSm": 6,
    "radiusMd": 8,
    "radiusLg": 12,
    "spacing": 8,
    "spacingLg": 16,
}


def _available_themes() -> dict[str, Path]:
    """Return {name: path} for every YAML theme file in the themes dir."""
    themes = {}
    if _THEMES_DIR.is_dir():
        for p in sorted(_THEMES_DIR.glob("*.yml")):
            themes[p.stem] = p
    return themes


class ThemeManager(QObject):
    """Loads colour themes from YAML files and exposes every token as a
    ``pyqtProperty`` so QML can bind to them.

    The single ``themeChanged`` signal is emitted whenever the active
    theme switches; all colour / typography / geometry properties notify
    on this signal so every binding refreshes at once.
    """

    themeChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._theme_name = ""
        self._colors: dict[str, QColor] = {}
        self._typography: dict[str, object] = dict(_DEFAULT_TYPOGRAPHY)
        self._geometry: dict[str, int] = dict(_DEFAULT_GEOMETRY)

        self._detect_and_apply()

        app = QGuiApplication.instance()
        if app:
            try:
                app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
            except AttributeError:
                pass

    # ── Public API ────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def setTheme(self, name: str):
        """Switch to the named theme (file stem, e.g. ``"dark"`` or ``"light"``)."""
        self._load(name)

    @pyqtSlot(result=list)
    def availableThemes(self) -> list[str]:
        """Return a list of theme names discovered in the themes directory."""
        return list(_available_themes().keys())

    # ── Internal ──────────────────────────────────────────────────────────

    def _detect_and_apply(self):
        """Pick a theme based on the system colour scheme."""
        name = "dark"
        app = QGuiApplication.instance()
        if app:
            try:
                scheme = app.styleHints().colorScheme()
                if scheme == Qt.ColorScheme.Light:
                    name = "light"
            except AttributeError:
                pass
        self._load(name)

    def _on_system_scheme_changed(self, scheme):
        try:
            if scheme == Qt.ColorScheme.Light:
                self._load("light")
            else:
                self._load("dark")
        except Exception as e:
            print(f"[Theme] Failed to switch on system scheme change: {e}", file=sys.stderr)

    def _load(self, name: str):
        themes = _available_themes()
        path = themes.get(name)
        if not path:
            print(f"[Theme] '{name}' not found in {_THEMES_DIR}, falling back to defaults", file=sys.stderr)
            self._apply_defaults()
            return

        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception as e:
            print(f"[Theme] Failed to read {path}: {e}", file=sys.stderr)
            self._apply_defaults()
            return

        colors_raw = data.get("colors", {})
        self._colors = {k: QColor(v) for k, v in colors_raw.items()}
        self._typography = {**_DEFAULT_TYPOGRAPHY, **data.get("typography", {})}
        self._geometry = {**_DEFAULT_GEOMETRY, **data.get("geometry", {})}
        self._theme_name = data.get("name", name)

        print(f"[Theme] Loaded: {self._theme_name} ({path.name})")
        self.themeChanged.emit()

    def _apply_defaults(self):
        self._colors = {k: QColor(v) for k, v in _DEFAULT_COLORS.items()}
        self._typography = dict(_DEFAULT_TYPOGRAPHY)
        self._geometry = dict(_DEFAULT_GEOMETRY)
        self._theme_name = "Dark"
        self.themeChanged.emit()

    def _c(self, key: str) -> QColor:
        return self._colors.get(key, QColor(_DEFAULT_COLORS.get(key, "#ff00ff")))

    # ══════════════════════════════════════════════════════════════════════
    #  QML properties — colours
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(str, notify=themeChanged)
    def themeName(self):
        return self._theme_name

    @pyqtProperty(QColor, notify=themeChanged)
    def bg(self):
        return self._c("bg")

    @pyqtProperty(QColor, notify=themeChanged)
    def surface(self):
        return self._c("surface")

    @pyqtProperty(QColor, notify=themeChanged)
    def surfaceHover(self):
        return self._c("surfaceHover")

    @pyqtProperty(QColor, notify=themeChanged)
    def border(self):
        return self._c("border")

    @pyqtProperty(QColor, notify=themeChanged)
    def borderSubtle(self):
        return self._c("borderSubtle")

    @pyqtProperty(QColor, notify=themeChanged)
    def text(self):
        return self._c("text")

    @pyqtProperty(QColor, notify=themeChanged)
    def textMuted(self):
        return self._c("textMuted")

    @pyqtProperty(QColor, notify=themeChanged)
    def accent(self):
        return self._c("accent")

    @pyqtProperty(QColor, notify=themeChanged)
    def accentHover(self):
        return self._c("accentHover")

    @pyqtProperty(QColor, notify=themeChanged)
    def success(self):
        return self._c("success")

    @pyqtProperty(QColor, notify=themeChanged)
    def warning(self):
        return self._c("warning")

    @pyqtProperty(QColor, notify=themeChanged)
    def error(self):
        return self._c("error")

    @pyqtProperty(QColor, notify=themeChanged)
    def running(self):
        return self._c("running")

    # ══════════════════════════════════════════════════════════════════════
    #  QML properties — typography
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(str, notify=themeChanged)
    def fontFamily(self):
        return self._typography.get("fontFamily", "Inter")

    @pyqtProperty(int, notify=themeChanged)
    def fontSizeXs(self):
        return int(self._typography.get("fontSizeXs", 12))

    @pyqtProperty(int, notify=themeChanged)
    def fontSizeSm(self):
        return int(self._typography.get("fontSizeSm", 14))

    @pyqtProperty(int, notify=themeChanged)
    def fontSizeMd(self):
        return int(self._typography.get("fontSizeMd", 15))

    @pyqtProperty(int, notify=themeChanged)
    def fontSizeLg(self):
        return int(self._typography.get("fontSizeLg", 18))

    # ══════════════════════════════════════════════════════════════════════
    #  QML properties — geometry
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(int, notify=themeChanged)
    def radiusSm(self):
        return int(self._geometry.get("radiusSm", 6))

    @pyqtProperty(int, notify=themeChanged)
    def radiusMd(self):
        return int(self._geometry.get("radiusMd", 8))

    @pyqtProperty(int, notify=themeChanged)
    def radiusLg(self):
        return int(self._geometry.get("radiusLg", 12))

    @pyqtProperty(int, notify=themeChanged)
    def spacing(self):
        return int(self._geometry.get("spacing", 8))

    @pyqtProperty(int, notify=themeChanged)
    def spacingLg(self):
        return int(self._geometry.get("spacingLg", 16))
