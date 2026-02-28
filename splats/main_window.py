"""Main PyQt6 application window"""

import sys
import json
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit,
    QGroupBox, QSpinBox, QComboBox, QLineEdit, QFrame, QScrollArea,
    QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QFont, QDesktopServices, QAction
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from .worker_threads import VideoProcessingWorker, ReconstructionWorker, PLYExportWorker, NerfstudioWorker
from .video_processor import VideoProcessor
from .project_manager import ProjectManager


class MainWindow(QMainWindow):
    """Main application window for video to Gaussian Splats conversion"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video to Gaussian Splats Converter")
        self.setMinimumSize(800, 600)
        
        # State
        self.video_path: Optional[str] = None
        self.frame_paths: list[str] = []
        self.splat_data: Optional[dict] = None
        self.workspace_dir: Path = Path.home() / ".splats_workspace"
        self.workspace_dir.mkdir(exist_ok=True)
        self.settings_file: Path = self.workspace_dir / "settings.json"
        
        # Stage tracking
        self.stage_widgets = {}
        self.stage_paths = {
            'frames': None,
            'feature_extract': None,
            'feature_match': None,
            'reconstruction': None,
            'training': None,
            'export': None
        }
        
        # Workers
        self.video_worker: Optional[VideoProcessingWorker] = None
        self.reconstruction_worker: Optional[ReconstructionWorker] = None
        self.export_worker: Optional[PLYExportWorker] = None
        self.nerfstudio_worker: Optional[NerfstudioWorker] = None
        
        # Project manager
        self.project = ProjectManager()
        
        self._setup_ui()
        self._setup_menu()
        self._load_settings()
        self._connect_settings_signals()  # Connect AFTER loading to avoid overwriting
        self._update_button_states()
    
    def closeEvent(self, event):
        """Handle window close - terminate running workers"""
        # Cancel any running workers
        any_running = False
        
        if self.nerfstudio_worker and self.nerfstudio_worker.isRunning():
            any_running = True
            self._log("⚠ Terminating nerfstudio pipeline (may see SIGTERM messages)...")
            self.nerfstudio_worker.cancel()
            self.nerfstudio_worker.wait(2000)  # Wait up to 2s
            if self.nerfstudio_worker.isRunning():
                self.nerfstudio_worker.terminate()  # Force terminate
        
        if self.video_worker and self.video_worker.isRunning():
            any_running = True
            self.video_worker.cancel()
            self.video_worker.wait(1000)
            if self.video_worker.isRunning():
                self.video_worker.terminate()
        
        if self.reconstruction_worker and self.reconstruction_worker.isRunning():
            any_running = True
            self.reconstruction_worker.cancel()
            self.reconstruction_worker.wait(1000)
            if self.reconstruction_worker.isRunning():
                self.reconstruction_worker.terminate()
        
        if self.export_worker and self.export_worker.isRunning():
            any_running = True
            self.export_worker.wait(1000)
            if self.export_worker.isRunning():
                self.export_worker.terminate()
        
        if any_running:
            # Note about termination messages
            import sys
            print("\n⚠ Note: SIGTERM/abort stack traces from pycolmap are normal during termination.", 
                  file=sys.stderr)
            print("   The processes have been terminated successfully.\n", file=sys.stderr)
        
        event.accept()
    
    def _setup_menu(self):
        """Setup menu bar with project management"""
        menubar = self.menuBar()
        
        # Project menu
        project_menu = menubar.addMenu("Project")
        
        new_action = QAction("New Project", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._on_new_project)
        project_menu.addAction(new_action)
        
        open_action = QAction("Open Project...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_project)
        project_menu.addAction(open_action)
        
        self._recent_menu = project_menu.addMenu("Recent Projects")
        self._update_recent_menu()
        
        project_menu.addSeparator()
        
        save_action = QAction("Save Project", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._on_save_project)
        project_menu.addAction(save_action)
        
        save_as_action = QAction("Save Project As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self._on_save_project_as)
        project_menu.addAction(save_as_action)

    def _setup_ui(self):
        """Setup the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        
        # Tab 1: Pipeline (input + options + progress + controls)
        editor_tab = QWidget()
        editor_layout = QVBoxLayout(editor_tab)
        
        settings_group = self._create_settings_section()
        editor_layout.addWidget(settings_group, stretch=0)
        
        progress_group = self._create_progress_section()
        editor_layout.addWidget(progress_group, stretch=1)
        
        control_layout = self._create_control_buttons()
        editor_layout.addLayout(control_layout, stretch=0)
        
        self.tabs.addTab(editor_tab, "Pipeline")
        
        # Tab 2: Video Preview
        video_tab = QWidget()
        video_layout = QVBoxLayout(video_tab)
        video_layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_widget = QVideoWidget()
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        video_layout.addWidget(self.video_widget, stretch=1)
        
        # Video info bar + playback controls
        controls_bar = QHBoxLayout()
        controls_bar.setContentsMargins(5, 2, 5, 5)
        
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedWidth(60)
        self.play_btn.clicked.connect(self._on_play_pause)
        controls_bar.addWidget(self.play_btn)
        
        from PyQt6.QtWidgets import QSlider
        self.video_slider = QSlider(Qt.Orientation.Horizontal)
        self.video_slider.sliderMoved.connect(self._on_video_seek)
        controls_bar.addWidget(self.video_slider)
        
        self.video_time_label = QLabel("0:00 / 0:00")
        self.video_time_label.setFixedWidth(100)
        controls_bar.addWidget(self.video_time_label)
        
        video_layout.addLayout(controls_bar, stretch=0)
        
        # Video info label at bottom of preview tab
        self.video_info_label = QLabel("No video loaded")
        self.video_info_label.setStyleSheet("background: rgba(0,0,0,0.6); color: #aaa; padding: 4px 8px; font-size: 11px;")
        video_layout.addWidget(self.video_info_label, stretch=0)
        
        self.media_player.positionChanged.connect(self._on_video_position_changed)
        self.media_player.durationChanged.connect(self._on_video_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        
        self.tabs.addTab(video_tab, "Video Preview")
        
        # Tab 3: 3D Viewer
        viewer_tab = QWidget()
        viewer_layout = QVBoxLayout(viewer_tab)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        
        self.viewer = QWebEngineView()
        viewer_path = Path(__file__).parent / "viewer" / "viewer.html"
        self.viewer.setUrl(QUrl.fromLocalFile(str(viewer_path)))
        viewer_layout.addWidget(self.viewer)
        
        self.tabs.addTab(viewer_tab, "3D Viewer")
        
        # Tab 4: Log
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(4, 4, 4, 4)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        self.tabs.addTab(log_tab, "Log")
        
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tabs)
    
    def _create_settings_section(self) -> QGroupBox:
        """Create merged video input + processing options section"""
        group = QGroupBox("Settings")
        layout = QVBoxLayout()
        
        # Video file selection
        file_layout = QHBoxLayout()
        self.video_path_label = QLabel("No video selected")
        self.video_path_label.setWordWrap(True)
        file_layout.addWidget(self.video_path_label)
        self.select_video_btn = QPushButton("Select Video")
        self.select_video_btn.clicked.connect(self._on_select_video)
        file_layout.addWidget(self.select_video_btn)
        layout.addLayout(file_layout)
        
        # Settings grid: 2 columns
        grid = QHBoxLayout()
        
        # Left column
        left_col = QVBoxLayout()
        
        sample_layout = QHBoxLayout()
        sample_layout.addWidget(QLabel("Sample Rate:"))
        self.sample_rate_spin = QSpinBox()
        self.sample_rate_spin.setMinimum(1)
        self.sample_rate_spin.setMaximum(60)
        self.sample_rate_spin.setValue(5)
        self.sample_rate_spin.setToolTip("Extract every Nth frame")
        sample_layout.addWidget(self.sample_rate_spin)
        left_col.addLayout(sample_layout)
        
        max_frames_layout = QHBoxLayout()
        max_frames_layout.addWidget(QLabel("Max Frames:"))
        self.max_frames_spin = QSpinBox()
        self.max_frames_spin.setMinimum(0)
        self.max_frames_spin.setMaximum(10000)
        self.max_frames_spin.setValue(300)
        self.max_frames_spin.setSpecialValueText("Unlimited")
        self.max_frames_spin.setToolTip("Maximum frames to extract (0 = unlimited)")
        max_frames_layout.addWidget(self.max_frames_spin)
        left_col.addLayout(max_frames_layout)
        
        grid.addLayout(left_col)
        
        # Right column
        right_col = QVBoxLayout()
        
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems([
            "Mock (Fast, test only)",
            "Nerfstudio (Real, GPU required)",
            "COLMAP (Requires install)"
        ])
        self.method_combo.setCurrentIndex(1)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        method_layout.addWidget(self.method_combo)
        right_col.addLayout(method_layout)
        
        iterations_layout = QHBoxLayout()
        iterations_layout.addWidget(QLabel("Iterations:"))
        self.iterations_spin = QSpinBox()
        self.iterations_spin.setMinimum(1000)
        self.iterations_spin.setMaximum(100000)
        self.iterations_spin.setValue(30000)
        self.iterations_spin.setSingleStep(5000)
        self.iterations_spin.setEnabled(False)
        iterations_layout.addWidget(self.iterations_spin)
        right_col.addLayout(iterations_layout)
        
        grid.addLayout(right_col)
        layout.addLayout(grid)
        
        # Output path
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output PLY:"))
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setText(str(self.workspace_dir / "output.ply"))
        output_layout.addWidget(self.output_path_edit)
        self.browse_output_btn = QPushButton("Browse")
        self.browse_output_btn.clicked.connect(self._on_browse_output)
        output_layout.addWidget(self.browse_output_btn)
        layout.addLayout(output_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_progress_section(self) -> QGroupBox:
        """Create progress tracking section with stage details"""
        group = QGroupBox("Pipeline Progress")
        layout = QVBoxLayout()
        
        # Pipeline status
        status_layout = QHBoxLayout()
        status_label = QLabel("Pipeline Status:")
        status_label.setStyleSheet("font-weight: bold;")
        self.progress_label = QLabel("Ready")
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.progress_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # Stage details
        stages_scroll = QScrollArea()
        stages_scroll.setWidgetResizable(True)
        stages_scroll.setMaximumHeight(300)
        stages_widget = QWidget()
        stages_layout = QVBoxLayout(stages_widget)
        
        # Create stage widgets (granular COLMAP phases)
        self.stage_widgets['frames'] = self._create_stage_widget("1. Frame Extraction", "frames")
        stages_layout.addWidget(self.stage_widgets['frames'])
        
        self.stage_widgets['feature_extract'] = self._create_stage_widget("2. Feature Extraction", "feature_extract")
        stages_layout.addWidget(self.stage_widgets['feature_extract'])
        
        self.stage_widgets['feature_match'] = self._create_stage_widget("3. Feature Matching", "feature_match")
        stages_layout.addWidget(self.stage_widgets['feature_match'])
        
        self.stage_widgets['reconstruction'] = self._create_stage_widget("4. Sparse Reconstruction", "reconstruction")
        stages_layout.addWidget(self.stage_widgets['reconstruction'])
        
        self.stage_widgets['training'] = self._create_stage_widget("5. Training (Splatfacto)", "training")
        stages_layout.addWidget(self.stage_widgets['training'])
        
        self.stage_widgets['export'] = self._create_stage_widget("6. Export PLY", "export")
        stages_layout.addWidget(self.stage_widgets['export'])
        
        stages_layout.addStretch()
        stages_scroll.setWidget(stages_widget)
        layout.addWidget(stages_scroll)
        
        group.setLayout(layout)
        return group
    
    def _create_stage_widget(self, name: str, stage_key: str) -> QFrame:
        """Create a collapsible stage widget with status and file browser"""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header with status
        header_layout = QHBoxLayout()
        
        status_label = QLabel("⚪")  # ⚪ pending, 🔵 running, ✅ done, ❌ error
        status_label.setProperty('stage_key', stage_key)
        status_label.setObjectName(f"{stage_key}_status")
        header_layout.addWidget(status_label)
        
        name_label = QLabel(f"<b>{name}</b>")
        header_layout.addWidget(name_label)
        
        header_layout.addStretch()
        
        # Info label
        info_label = QLabel("Pending")
        info_label.setObjectName(f"{stage_key}_info")
        header_layout.addWidget(info_label)
        
        # File browser button
        browse_btn = QPushButton("📁 View Files")
        browse_btn.setMaximumWidth(100)
        browse_btn.setEnabled(False)
        browse_btn.setObjectName(f"{stage_key}_browse")
        browse_btn.clicked.connect(lambda: self._open_stage_folder(stage_key))
        header_layout.addWidget(browse_btn)
        
        layout.addLayout(header_layout)
        
        # Details (initially hidden)
        details_label = QLabel("")
        details_label.setWordWrap(True)
        details_label.setObjectName(f"{stage_key}_details")
        details_label.hide()
        layout.addWidget(details_label)
        
        return frame
    
    def _open_stage_folder(self, stage_key: str):
        """Open file browser for stage output folder"""
        path = self.stage_paths.get(stage_key)
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self._log(f"Stage folder not found: {path}")
    
    def _create_control_buttons(self) -> QHBoxLayout:
        """Create control buttons"""
        layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Conversion")
        self.start_btn.clicked.connect(self._on_start_conversion)
        layout.addWidget(self.start_btn)
        
        self.resume_training_btn = QPushButton("Re-export from Checkpoint")
        self.resume_training_btn.setToolTip("Skip data processing and training; re-export PLY from saved checkpoint")
        self.resume_training_btn.clicked.connect(self._on_resume_from_training)
        self.resume_training_btn.setEnabled(False)
        layout.addWidget(self.resume_training_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        layout.addWidget(self.cancel_btn)
        
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(self.clear_btn)
        
        layout.addStretch()
        return layout
    
    
    def _update_button_states(self):
        """Update button enabled/disabled states"""
        has_video = self.video_path is not None
        is_processing = (
            (self.video_worker is not None and self.video_worker.isRunning()) or
            (self.reconstruction_worker is not None and self.reconstruction_worker.isRunning()) or
            (self.export_worker is not None and self.export_worker.isRunning()) or
            (self.nerfstudio_worker is not None and self.nerfstudio_worker.isRunning())
        )
        can_resume_training = (
            not is_processing and
            self.project.is_open and
            self.project.can_resume_from_training()
        )
        
        self.select_video_btn.setEnabled(not is_processing)
        self.start_btn.setEnabled(has_video and not is_processing)
        self.resume_training_btn.setEnabled(can_resume_training)
        self.cancel_btn.setEnabled(is_processing)
        self.sample_rate_spin.setEnabled(not is_processing)
        self.max_frames_spin.setEnabled(not is_processing)
        self.method_combo.setEnabled(not is_processing)
        self.iterations_spin.setEnabled(not is_processing and self.method_combo.currentIndex() == 1)
        self.output_path_edit.setEnabled(not is_processing)
        self.browse_output_btn.setEnabled(not is_processing)
    
    def _on_method_changed(self):
        """Handle method combo box change"""
        # Enable/disable iterations spin based on nerfstudio selection
        is_nerfstudio = self.method_combo.currentIndex() == 1
        self.iterations_spin.setEnabled(is_nerfstudio)
        
        # Update sample rate and max frames visibility for nerfstudio
        # (nerfstudio handles this internally)
        if is_nerfstudio:
            self.sample_rate_spin.setToolTip("Not used with nerfstudio (it extracts frames automatically)")
            self.max_frames_spin.setToolTip("Target number of frames for processing (lower = faster for debugging)")
        else:
            self.sample_rate_spin.setToolTip("Extract every Nth frame (1 = all frames)")
            self.max_frames_spin.setToolTip("Maximum frames to extract (0 = unlimited)")
    
    def _update_stage(self, stage_key: str, status: str, info: str = "", details: str = "", path: str = None):
        """Update stage widget status
        
        Args:
            stage_key: Stage identifier (frames, colmap, training, export)
            status: pending, running, done, error
            info: Short status text
            details: Detailed information (optional)
            path: File path for browse button (optional)
        """
        status_icons = {
            'pending': '⚪',
            'running': '🔵',
            'done': '✅',
            'error': '❌'
        }
        
        frame = self.stage_widgets.get(stage_key)
        if not frame:
            return
        
        # Debug: Log training stage updates
        if stage_key == 'training':
            print(f"[UI DEBUG] _update_stage: status={status}, info={info}, details={details[:50] if details else ''}")
        
        # Update status icon
        status_label = frame.findChild(QLabel, f"{stage_key}_status")
        if status_label:
            status_label.setText(status_icons.get(status, '⚪'))
        
        # Update info
        info_label = frame.findChild(QLabel, f"{stage_key}_info")
        if info_label:
            info_label.setText(info)
        
        # Update details
        details_label = frame.findChild(QLabel, f"{stage_key}_details")
        if details_label and details:
            details_label.setText(details)
            details_label.show()
        
        # Update browse button
        if path:
            self.stage_paths[stage_key] = path
            browse_btn = frame.findChild(QPushButton, f"{stage_key}_browse")
            if browse_btn:
                browse_btn.setEnabled(True)
    
    def _log(self, message: str):
        """Add message to log"""
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def _on_select_video(self):
        """Handle video selection"""
        # Start dialog in directory of last video if available
        start_dir = str(Path.home())
        if self.video_path:
            start_dir = str(Path(self.video_path).parent)
        
        VIDEO_EXTS = [
            "mp4", "mov", "avi", "mkv", "webm", "flv", "wmv", "m4v", "mts", "ts",
            "mpg", "mpeg", "3gp", "3g2", "mxf", "dv", "braw", "r3d",
            "vob", "ogv", "gif", "asf", "rm", "swf", "divx", "f4v",
        ]
        # Include both lower and upper case for native dialogs (case-sensitive on Linux)
        patterns = []
        for ext in VIDEO_EXTS:
            patterns.append(f"*.{ext}")
            upper = ext.upper()
            if upper != ext:
                patterns.append(f"*.{upper}")
        filter_str = "Video Files (" + " ".join(patterns) + ");;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            start_dir,
            filter_str,
        )
        
        if file_path:
            self.video_path = file_path
            self.video_path_label.setText(f"Video: {Path(file_path).name}")
            self._log(f"Selected video: {file_path}")
            self._load_video_preview(file_path)
            
            # Load video metadata
            try:
                processor = VideoProcessor()
                info = processor.get_video_info(file_path)
                info_text = (
                    f"Resolution: {info['width']}x{info['height']} | "
                    f"FPS: {info['fps']:.2f} | "
                    f"Frames: {info['frame_count']} | "
                    f"Duration: {info['duration']:.2f}s"
                )
                self.video_info_label.setText(info_text)
                self._log(f"Video info: {info_text}")
            except Exception as e:
                self._log(f"Error loading video metadata: {e}")
            
            # Save settings
            self._save_settings()
            
            self._update_button_states()
    
    def _on_browse_output(self):
        """Handle output path browsing"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save PLY File",
            self.output_path_edit.text(),
            "PLY Files (*.ply);;All Files (*)"
        )
        
        if file_path:
            self.output_path_edit.setText(file_path)
    
    def _on_start_conversion(self):
        """Start the conversion pipeline"""
        if not self.video_path:
            self._log("Error: No video selected")
            return
        
        self._log("=" * 50)
        self._log("Starting conversion pipeline...")
        self.progress_label.setText("Processing...")
        
        method_idx = self.method_combo.currentIndex()
        
        # Nerfstudio: full pipeline in one worker
        if method_idx == 1:
            self._start_nerfstudio_pipeline()
        else:
            # Mock/COLMAP: multi-stage pipeline
            self._start_video_processing()
    
    def _start_video_processing(self):
        """Start video frame extraction"""
        self._log("Stage 1/3: Extracting frames from video...")
        
        frames_dir = self.workspace_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        
        # Clear previous frames
        for f in frames_dir.glob("*.png"):
            f.unlink()
        
        sample_rate = self.sample_rate_spin.value()
        max_frames = self.max_frames_spin.value() if self.max_frames_spin.value() > 0 else None
        
        self.video_worker = VideoProcessingWorker(
            self.video_path,
            str(frames_dir),
            sample_rate=sample_rate,
            max_frames=max_frames
        )
        
        self.video_worker.progress.connect(self._on_video_progress)
        self.video_worker.finished.connect(self._on_video_finished)
        self.video_worker.error.connect(self._on_error)
        
        self.video_worker.start()
        self._update_button_states()
    
    def _on_video_progress(self, data: dict):
        """Handle video processing progress"""
        stage = data['stage']
        current = data.get('current', 0)
        total = data.get('total', 100)
        
        self.progress_label.setText(f"Processing video frames...")
    
    def _on_video_finished(self, result: dict):
        """Handle video processing completion"""
        self.video_worker = None
        
        if result['success']:
            self.frame_paths = result['frame_paths']
            self._log(f"Extracted {len(self.frame_paths)} frames")
            
            # Start reconstruction
            self._start_reconstruction()
        else:
            self._log(f"Error: {result['error']}")
            self.progress_label.setText("Failed")
            self._update_button_states()
    
    def _start_reconstruction(self):
        """Start 3D reconstruction"""
        self._log("Stage 2/3: Performing 3D reconstruction...")
        
        method_idx = self.method_combo.currentIndex()
        method = "mock" if method_idx == 0 else "colmap"
        
        self.reconstruction_worker = ReconstructionWorker(
            self.frame_paths,
            str(self.workspace_dir / "reconstruction"),
            method=method
        )
        
        self.reconstruction_worker.progress.connect(self._on_reconstruction_progress)
        self.reconstruction_worker.finished.connect(self._on_reconstruction_finished)
        self.reconstruction_worker.error.connect(self._on_error)
        
        self.reconstruction_worker.start()
    
    def _on_reconstruction_progress(self, data: dict):
        """Handle reconstruction progress"""
        stage = data['stage']
        stage = data['stage']
        self.progress_label.setText(f"Running {stage}...")
    
    def _on_reconstruction_finished(self, result: dict):
        """Handle reconstruction completion"""
        self.reconstruction_worker = None
        
        if result['success']:
            self.splat_data = result['data']
            num_points = self.splat_data.get('num_points', 0)
            self._log(f"Generated {num_points} Gaussian splats")
            
            # Start PLY export
            self._start_ply_export()
        else:
            self._log(f"Error: {result['error']}")
            self.progress_label.setText("Failed")
            self._update_button_states()
    
    def _start_ply_export(self):
        """Start PLY export"""
        self._log("Stage 3/3: Exporting to PLY format...")
        
        output_path = self.output_path_edit.text()
        
        self.export_worker = PLYExportWorker(
            self.splat_data,
            output_path
        )
        
        self.export_worker.progress.connect(self._on_export_progress)
        self.export_worker.finished.connect(self._on_export_finished)
        self.export_worker.error.connect(self._on_error)
        
        self.export_worker.start()
    
    def _on_export_progress(self, data: dict):
        """Handle export progress"""
        stage = data['stage']
        self.progress_label.setText("Exporting PLY...")
    
    def _on_export_finished(self, result: dict):
        """Handle export completion"""
        self.export_worker = None
        
        if result['success']:
            output_path = result['output_path']
            self._log(f"✓ Conversion complete!")
            self._log(f"Output saved to: {output_path}")
            self.progress_label.setText("✓ Complete")
        else:
            self._log(f"Error: {result['error']}")
            self.progress_label.setText("Failed")
        
        self._update_button_states()
    
    def _on_error(self, error_msg: str):
        """Handle worker thread errors"""
        self._log(f"Error: {error_msg}")
        self.progress_label.setText("Error")
        self._update_button_states()
    
    def _on_cancel(self):
        """Cancel ongoing operations"""
        self._log("⚠ Cancelling operations (terminating processes)...")
        
        # Cancel and terminate nerfstudio worker
        if self.nerfstudio_worker and self.nerfstudio_worker.isRunning():
            self.nerfstudio_worker.cancel()
            self.nerfstudio_worker.wait(2000)  # Wait up to 2s
            if self.nerfstudio_worker.isRunning():
                self._log("⚠ Force terminating nerfstudio worker...")
                self.nerfstudio_worker.terminate()
                self.nerfstudio_worker.wait(1000)
        
        # Cancel and terminate video worker
        if self.video_worker and self.video_worker.isRunning():
            self.video_worker.cancel()
            self.video_worker.wait(1000)
            if self.video_worker.isRunning():
                self.video_worker.terminate()
                self.video_worker.wait(500)
        
        # Cancel and terminate reconstruction worker
        if self.reconstruction_worker and self.reconstruction_worker.isRunning():
            self.reconstruction_worker.cancel()
            self.reconstruction_worker.wait(1000)
            if self.reconstruction_worker.isRunning():
                self.reconstruction_worker.terminate()
                self.reconstruction_worker.wait(500)
        
        # Wait for export worker (no cancel method)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.wait(1000)
            if self.export_worker.isRunning():
                self.export_worker.terminate()
                self.export_worker.wait(500)
        
        self._log("✓ Operations cancelled")
        self.progress_label.setText("Cancelled")
        
        # Reset all stages to idle
        for stage_key in self.stage_widgets.keys():
            self._update_stage(stage_key, 'idle', 'Cancelled', details='')
        
        self._update_button_states()
    
    def _on_clear(self):
        """Clear all data and reset"""
        self.video_path = None
        self.frame_paths = []
        self.splat_data = None
        
        self.video_path_label.setText("No video selected")
        self.video_info_label.setText("Video info: N/A")
        self.progress_label.setText("Ready")
        self.log_text.clear()
        
        # Reset stages
        for stage_key in ['frames', 'feature_extract', 'feature_match', 'reconstruction', 'training', 'export']:
            self._update_stage(stage_key, 'pending', 'Pending')
            self.stage_paths[stage_key] = None
            if stage_key in self.stage_widgets:
                browse_btn = self.stage_widgets[stage_key].findChild(QPushButton, f"{stage_key}_browse")
                if browse_btn:
                    browse_btn.setEnabled(False)
        
        self._log("Cleared all data")
        self._update_button_states()
    
    def _start_nerfstudio_pipeline(self):
        """Start nerfstudio full pipeline (data processing + training + export)"""
        self._log("Starting Nerfstudio pipeline...")
        self._log("⚠ This will take 10-30 minutes depending on GPU and settings")
        
        # Initialize/reset project for fresh run
        if not self.project.is_open:
            self.project.new_project(video_path=self.video_path, settings=self._current_settings())
        else:
            self.project.update_settings(self._current_settings())
            if self.video_path:
                self.project.update_input(self.video_path)
            # Reset all stages for fresh run
            from .project_manager import STAGE_ORDER
            for s in STAGE_ORDER:
                self.project.update_stage(s, 'pending')
        
        # Initialize stage states
        self._update_stage('frames', 'pending', 'Waiting...')
        self._update_stage('feature_extract', 'pending', 'Waiting...')
        self._update_stage('feature_match', 'pending', 'Waiting...')
        self._update_stage('reconstruction', 'pending', 'Waiting...')
        self._update_stage('training', 'pending', 'Waiting...')
        self._update_stage('export', 'pending', 'Waiting...')
        
        max_iterations = self.iterations_spin.value()
        max_frames = self.max_frames_spin.value()
        if max_frames == 0:
            max_frames = 300  # Default if set to "Unlimited"
        output_path = self.output_path_edit.text()
        workspace = self.workspace_dir / "nerfstudio"
        
        self.nerfstudio_worker = NerfstudioWorker(
            video_path=self.video_path,
            workspace_dir=str(workspace),
            output_ply_path=output_path,
            max_iterations=max_iterations,
            use_video_directly=True,
            num_frames_target=max_frames
        )
        
        self.nerfstudio_worker.progress.connect(self._on_nerfstudio_progress)
        self.nerfstudio_worker.finished.connect(self._on_nerfstudio_finished)
        self.nerfstudio_worker.error.connect(self._on_error)
        self.nerfstudio_worker.log.connect(self._log)
        self.nerfstudio_worker.stage_data_completed.connect(self._on_stage_data_completed)
        self.nerfstudio_worker.stage_training_completed.connect(self._on_stage_training_completed)
        
        self.nerfstudio_worker.start()
        self._update_button_states()
    
    def _on_nerfstudio_progress(self, data: dict):
        """Handle nerfstudio progress updates"""
        stage = data['stage']
        progress = data.get('progress', 0.0)
        substage = data.get('substage', '')
        progress_percent = int(progress * 100)
        
        # Debug: Print raw data for training
        if "Training" in stage:
            print(f"[UI DEBUG] stage='{stage}', substage='{substage}', progress={progress}")
        
        # Update simple status label (no percentages)
        if "Data" in stage:
            if progress < 0.15:
                self.progress_label.setText("Extracting frames...")
            elif progress < 0.30:
                self.progress_label.setText("Extracting features...")
            elif progress < 0.50:
                self.progress_label.setText("Matching features...")
            elif progress < 1.0:
                self.progress_label.setText("Building reconstruction...")
            else:
                self.progress_label.setText("Data processing complete")
        elif "Training" in stage:
            self.progress_label.setText("Training Gaussian Splatting model...")
        elif "Export" in stage:
            self.progress_label.setText("Exporting PLY...")
        
        # Map to stage widgets
        if "Data" in stage:  # Matches "Data" or "Data Processing"
            status = 'running' if progress < 1.0 else 'done'
            info_text = substage[:60] if substage else f"{progress_percent}%"  # Truncate long messages
            
            # Frame extraction phase
            if any(x in substage.lower() for x in ["extracting frames", "converting video"]) or (progress < 0.15 and "colmap" not in substage.lower()):
                # Extract frame count if available (from directory monitoring)
                import re
                frame_match = re.search(r'extracting frames:\s*(\d+)', substage.lower())
                
                # Get target from UI settings
                target_frames = self.max_frames_spin.value() or 300
                
                if frame_match:
                    frame_count = frame_match.group(1)
                    display_text = f"{frame_count} extracted"
                    details_text = f"Extracting frames from video (target: {target_frames})"
                else:
                    display_text = "Starting"
                    details_text = f"Extracting frames from video (target: {target_frames})"
                
                self._update_stage('frames', 'running', display_text,
                                 details=details_text,
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "images"))
            
            # Frame extraction complete
            elif "frame extraction complete" in substage.lower() or ("done converting" in substage.lower() and "feature" not in substage.lower()):
                self._update_stage('frames', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "images"))
            
            # Feature extraction (COLMAP phase 1)
            elif "extracting features" in substage.lower():
                self._update_stage('frames', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "images"))
                
                # Extract counts if available: "[175/317]"
                count_match = re.search(r'\[(\d+)/(\d+)\]', substage)
                if count_match:
                    current = count_match.group(1)
                    total = count_match.group(2)
                    display_text = f"{current}/{total}"
                    percent = int((int(current) / int(total)) * 100)
                    details_text = f"Processing {total} images - extracting SIFT features ({percent}%)"
                else:
                    display_text = "Starting"
                    details_text = "Extracting SIFT features from images"
                
                self._update_stage('feature_extract', 'running', display_text,
                                 details=details_text,
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            # Feature matching (COLMAP phase 2)
            elif "matching features" in substage.lower():
                # Mark previous stages done
                self._update_stage('frames', 'done', "Complete")
                self._update_stage('feature_extract', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
                
                # Extract counts if available: "[175/317]"
                import re
                count_match = re.search(r'\[(\d+)/(\d+)\]', substage)
                if count_match:
                    current = count_match.group(1)
                    total = count_match.group(2)
                    display_text = f"{current}/{total}"
                    percent = int((int(current) / int(total)) * 100)
                    details_text = f"Processing {total} images - matching features ({percent}%)"
                else:
                    display_text = "Starting"
                    details_text = "Matching features between image pairs"
                
                self._update_stage('feature_match', 'running', display_text,
                                 details=details_text,
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            # Sparse reconstruction / bundle adjustment / refining (COLMAP phase 3)
            elif any(x in substage.lower() for x in ["reconstruction", "bundle adjustment", "refining intrinsic", "registering"]):
                # Mark previous stages done
                self._update_stage('frames', 'done', "Complete")
                self._update_stage('feature_extract', 'done', "Complete")
                self._update_stage('feature_match', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
                
                import re
                # Extract registered image count: "[N images]" or "num_reg_frames"
                count_match = re.search(r'\[(\d+)\s+images?\]|\[(\d+)/\d+\]', substage)
                
                if "bundle adjustment" in substage.lower():
                    display_text = "Optimizing"
                    details_text = "Bundle adjustment - optimizing camera poses and 3D points"
                elif "refining" in substage.lower():
                    display_text = "Refining"
                    details_text = "Refining camera intrinsic parameters"
                elif "reconstruction" in substage.lower() or "registering" in substage.lower():
                    if count_match:
                        num = count_match.group(1) or count_match.group(2)
                        display_text = f"{num} registered"
                        details_text = f"Registered {num} images - building 3D structure"
                    else:
                        display_text = "Starting"
                        details_text = "Registering images and building sparse 3D map"
                else:
                    display_text = "Running"
                    details_text = f"Sparse reconstruction in progress"
                
                self._update_stage('reconstruction', 'running', display_text,
                                 details=details_text,
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            # Feature extraction complete
            elif "feature extraction complete" in substage.lower():
                self._update_stage('feature_extract', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            # Feature matching complete
            elif "feature matching complete" in substage.lower():
                self._update_stage('feature_match', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            # COLMAP complete (all phases)
            elif "colmap" in substage.lower() and "complete" in substage.lower():
                self._update_stage('frames', 'done', "Complete")
                self._update_stage('feature_extract', 'done', "Complete")
                self._update_stage('feature_match', 'done', "Complete")
                self._update_stage('reconstruction', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            # Data processing complete
            elif progress >= 1.0 or "all done" in substage.lower() or "congrats" in substage.lower():
                self._update_stage('frames', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "images"))
                self._update_stage('feature_extract', 'done', "Complete")
                self._update_stage('feature_match', 'done', "Complete")
                self._update_stage('reconstruction', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
        
        elif "Training" in stage:
            status = 'running' if progress < 1.0 else 'done'
            
            # Extract step info if available
            import re
            step_match = re.search(r'Step (\d+)/(\d+)', substage)
            if step_match:
                current_step = step_match.group(1)
                total_steps = step_match.group(2)
                info_text = f"{current_step}/{total_steps}"
                details_text = f"Training {total_steps} iterations - splatfacto model ({progress_percent}%)"
                
                # Debug: Log every update
                print(f"[UI] Training progress: {info_text} ({progress_percent}%)")
            else:
                info_text = substage[:50] if substage else "Running"
                details_text = f"Training Gaussian Splatting model"
            
            self._update_stage('training', status, info_text,
                             details=details_text,
                             path=str(self.workspace_dir / "nerfstudio" / "outputs"))
            
            # Ensure previous stages marked complete
            if progress > 0:
                self._update_stage('frames', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "images"))
                self._update_stage('feature_extract', 'done', "Complete")
                self._update_stage('feature_match', 'done', "Complete")
                self._update_stage('reconstruction', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "nerfstudio_data" / "colmap"))
            
            if progress >= 1.0:
                self._update_stage('training', 'done', "Complete")
        
        elif "Export" in stage:
            status = 'running' if progress < 1.0 else 'done'
            info_text = substage[:50] if substage else f"{progress_percent}%"
            self._update_stage('export', status, info_text,
                             details=f"Exporting PLY: {substage}",
                             path=str(Path(self.output_path_edit.text()).parent))
            
            # Ensure previous stages complete
            if progress > 0:
                self._update_stage('training', 'done', "Complete",
                                 path=str(self.workspace_dir / "nerfstudio" / "outputs"))
            
            if progress >= 1.0:
                self._update_stage('export', 'done', "Complete")
    
    def _on_nerfstudio_finished(self, result: dict):
        """Handle nerfstudio pipeline completion"""
        self.nerfstudio_worker = None
        
        if result['success']:
            output_path = result['output_path']
            self._log("=" * 50)
            self._log("✓ Nerfstudio pipeline complete!")
            self._log(f"Output PLY: {output_path}")
            if result.get('config_path'):
                self._log(f"Model config: {result['config_path']}")
            self.progress_label.setText("✓ Pipeline complete")
            
            # Mark all stages complete
            self._update_stage('frames', 'done', 'Complete')
            self._update_stage('feature_extract', 'done', 'Complete')
            self._update_stage('feature_match', 'done', 'Complete')
            self._update_stage('reconstruction', 'done', 'Complete')
            self._update_stage('training', 'done', 'Complete')
            self._update_stage('export', 'done', 'Complete',
                             path=str(Path(output_path).parent))
            
            # Save project with export result
            if not self.project.is_open:
                self.project.new_project(video_path=self.video_path, settings=self._current_settings())
            self.project.update_stage('export', 'completed', ply_path=output_path)
            if not self.project.project_path:
                # Auto-create project file next to video or in workspace
                stem = Path(self.video_path).stem if self.video_path else "splats"
                auto_path = self.workspace_dir / f"{stem}.splatproj"
                self.project.save_project(str(auto_path))
                self._log(f"✓ Project auto-saved: {auto_path.name}")
                self._update_title()
                self._update_recent_menu()
            else:
                self._auto_save_project()
            
            # Load PLY in viewer
            self._load_ply_in_viewer(output_path)
        else:
            self._log(f"✗ Pipeline failed: {result['error']}")
            self.progress_label.setText("✗ Pipeline failed")
            
            # Mark current stage as error (find first non-done stage)
            stages = ['frames', 'feature_extract', 'feature_match', 'reconstruction', 'training', 'export']
            for stage_key in stages:
                frame = self.stage_widgets.get(stage_key)
                if frame:
                    status_label = frame.findChild(QLabel, f"{stage_key}_status")
                    if status_label and ('⚪' in status_label.text() or '🔵' in status_label.text()):
                        # This stage was pending or running when error occurred
                        self._update_stage(stage_key, 'error', 'Failed')
                        break
        
        self._update_button_states()
    
    # ── Project Management ─────────────────────────────────────────────────────

    def _on_new_project(self):
        """Create new empty project"""
        self.project.new_project(video_path=self.video_path, settings=self._current_settings())
        self._on_save_project_as()

    def _on_open_project(self):
        """Open project from file dialog"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", str(Path.home()),
            "Splat Projects (*.splatproj);;All Files (*)"
        )
        if path:
            self._load_project_file(path)

    def _on_save_project(self):
        """Save current project (save as if no path set)"""
        if not self.project.is_open:
            self.project.new_project(video_path=self.video_path, settings=self._current_settings())
        if not self.project.project_path:
            self._on_save_project_as()
        else:
            self.project.update_settings(self._current_settings())
            if self.video_path:
                self.project.update_input(self.video_path)
            self.project.save_project()
            self._log(f"✓ Project saved: {self.project.project_path.name}")
            self._update_title()

    def _on_save_project_as(self):
        """Save project with new path"""
        # Suggest name from video filename
        suggested = str(Path.home() / "splats_project.splatproj")
        if self.video_path:
            stem = Path(self.video_path).stem
            suggested = str(Path.home() / f"{stem}.splatproj")
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", suggested,
            "Splat Projects (*.splatproj);;All Files (*)"
        )
        if path:
            if not path.endswith('.splatproj'):
                path += '.splatproj'
            if not self.project.is_open:
                self.project.new_project(video_path=self.video_path, settings=self._current_settings())
            self.project.update_settings(self._current_settings())
            if self.video_path:
                self.project.update_input(self.video_path)
            self.project.save_project(path)
            self._log(f"✓ Project saved: {path}")
            self._update_title()
            self._update_recent_menu()

    def _load_project_file(self, path: str):
        """Load a project file and restore UI state"""
        try:
            data = self.project.load_project(path)
            self._log(f"✓ Project loaded: {Path(path).name}")
            self._update_title()
            self._update_recent_menu()

            # Restore video path
            vid = self.project.video_path
            if vid and Path(vid).exists():
                self.video_path = vid
                self.video_path_label.setText(f"Video: {Path(vid).name}")
                self._load_video_preview(vid)
                try:
                    processor = VideoProcessor()
                    info = processor.get_video_info(vid)
                    self.video_info_label.setText(
                        f"Resolution: {info['width']}x{info['height']} | "
                        f"FPS: {info['fps']:.2f} | "
                        f"Frames: {info['frame_count']} | "
                        f"Duration: {info['duration']:.2f}s"
                    )
                except Exception:
                    pass

            # Restore settings
            s = self.project.settings
            if s.get('reconstruction_method') is not None:
                self.method_combo.setCurrentIndex(s['reconstruction_method'])
            if s.get('training_iterations'):
                self.iterations_spin.setValue(s['training_iterations'])
            if s.get('sample_rate'):
                self.sample_rate_spin.setValue(s['sample_rate'])
            if s.get('max_frames'):
                self.max_frames_spin.setValue(s['max_frames'])

            # Restore stage indicators
            stages_map = {
                'frames': 'frames',
                'feature_extract': 'feature_extract',
                'feature_match': 'feature_match',
                'reconstruction': 'reconstruction',
                'training': 'training',
                'export': 'export',
            }
            for stage_key, widget_key in stages_map.items():
                stage = self.project.get_stage(stage_key)
                status = stage.get('status', 'pending')
                if status == 'completed':
                    path_val = stage.get('path') or stage.get('ply_path') or stage.get('checkpoint_dir')
                    self._update_stage(widget_key, 'done', 'Complete', path=path_val)
                    if path_val:
                        self.stage_paths[stage_key] = path_val

            # Load PLY if available
            ply = self.project.get_export_ply()
            if ply and Path(ply).exists():
                self._load_ply_in_viewer(ply)
                self._log(f"✓ Loaded existing PLY: {Path(ply).name}")

            # Show pipeline status
            resume_point = self.project.get_resume_point()
            if resume_point is None:
                self._log("✓ All stages complete")
                self.progress_label.setText("✓ Pipeline complete (loaded)")
            elif resume_point == 'frames':
                self._log("ℹ No stages completed yet")
            else:
                self._log(f"ℹ Completed up to: {resume_point} stage pending")
                if self.project.can_resume_from_training():
                    self._log("→ Use 'Re-export from Checkpoint' to skip training")

            self._update_button_states()

        except Exception as e:
            self._log(f"✗ Failed to load project: {e}")

    def _auto_save_project(self):
        """Auto-save project if one is open"""
        if self.project.is_open:
            self.project.update_settings(self._current_settings())
            if self.video_path:
                self.project.update_input(self.video_path)
            self.project.save_project()

    def _current_settings(self) -> dict:
        """Return current UI settings as dict"""
        return {
            'reconstruction_method': self.method_combo.currentIndex(),
            'training_iterations': self.iterations_spin.value(),
            'sample_rate': self.sample_rate_spin.value(),
            'max_frames': self.max_frames_spin.value(),
        }

    def _update_title(self):
        """Update window title with project name"""
        if self.project.project_path:
            self.setWindowTitle(f"Video to Gaussian Splats - {self.project.project_name}")
        else:
            self.setWindowTitle("Video to Gaussian Splats Converter")

    def _update_recent_menu(self):
        """Populate Recent Projects submenu"""
        self._recent_menu.clear()
        recent = self.project.get_recent_projects()
        if not recent:
            self._recent_menu.addAction("(none)").setEnabled(False)
            return
        for path in recent:
            action = QAction(Path(path).name, self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self._load_project_file(p))
            self._recent_menu.addAction(action)

    def _on_resume_from_training(self):
        """Resume pipeline from existing checkpoint (skip data + training)"""
        checkpoint = self.project.get_training_checkpoint()
        if not checkpoint or not Path(checkpoint).exists():
            self._log("✗ No valid checkpoint found in project")
            return
        
        self._log(f"[Resume] Starting from checkpoint: {Path(checkpoint).name}")
        self._log("⚡ Skipping data processing and training")
        
        # Initialize stage states - mark completed stages, pending export
        self._update_stage('frames', 'done', 'Skipped')
        self._update_stage('feature_extract', 'done', 'Skipped')
        self._update_stage('feature_match', 'done', 'Skipped')
        self._update_stage('reconstruction', 'done', 'Skipped')
        self._update_stage('training', 'done', 'Skipped')
        self._update_stage('export', 'pending', 'Waiting...')
        
        output_path = self.output_path_edit.text()
        workspace = self.workspace_dir / "nerfstudio"
        
        self.nerfstudio_worker = NerfstudioWorker(
            video_path=self.video_path or "",
            workspace_dir=str(workspace),
            output_ply_path=output_path,
            max_iterations=self.iterations_spin.value(),
            use_video_directly=True,
            num_frames_target=self.max_frames_spin.value() or 300,
            skip_data_processing=True,
            skip_training=True,
            existing_checkpoint=checkpoint,
            existing_data_dir=self.project.get_stage('reconstruction').get('path'),
        )
        
        self.nerfstudio_worker.progress.connect(self._on_nerfstudio_progress)
        self.nerfstudio_worker.finished.connect(self._on_nerfstudio_finished)
        self.nerfstudio_worker.error.connect(self._on_error)
        self.nerfstudio_worker.log.connect(self._log)
        self.nerfstudio_worker.stage_data_completed.connect(self._on_stage_data_completed)
        self.nerfstudio_worker.stage_training_completed.connect(self._on_stage_training_completed)
        
        self.nerfstudio_worker.start()
        self._update_button_states()

    # ── Project signal handlers ────────────────────────────────────────────────

    def _on_stage_data_completed(self, data_dir: str):
        """Save data stage completion to project"""
        if not self.project.is_open:
            self.project.new_project(video_path=self.video_path, settings=self._current_settings())
        images_path = str(Path(data_dir) / "images")
        colmap_path = str(Path(data_dir) / "colmap")
        self.project.update_stage('frames', 'completed', path=images_path)
        self.project.update_stage('feature_extract', 'completed')
        self.project.update_stage('feature_match', 'completed')
        self.project.update_stage('reconstruction', 'completed', path=colmap_path)
        self._auto_save_project()

    def _on_stage_training_completed(self, checkpoint_dir: str, latest_checkpoint: str):
        """Save training stage completion to project"""
        if not self.project.is_open:
            self.project.new_project(video_path=self.video_path, settings=self._current_settings())
        self.project.update_stage(
            'training', 'completed',
            checkpoint_dir=checkpoint_dir,
            latest_checkpoint=latest_checkpoint,
        )
        self._auto_save_project()
        self._update_button_states()

    # ── Settings (legacy JSON) ─────────────────────────────────────────────────

    def _connect_settings_signals(self):
        """Connect UI controls to save settings on change"""
        self.method_combo.currentIndexChanged.connect(self._save_settings)
        self.iterations_spin.valueChanged.connect(self._save_settings)
        self.sample_rate_spin.valueChanged.connect(self._save_settings)
        self.max_frames_spin.valueChanged.connect(self._save_settings)
    
    def _load_settings(self):
        """Load settings from file"""
        if not self.settings_file.exists():
            return
        
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
            
            # Load UI settings
            if 'reconstruction_method' in settings:
                self.method_combo.setCurrentIndex(settings['reconstruction_method'])
            
            if 'training_iterations' in settings:
                self.iterations_spin.setValue(settings['training_iterations'])
            
            if 'sample_rate' in settings:
                self.sample_rate_spin.setValue(settings['sample_rate'])
            
            if 'max_frames' in settings:
                self.max_frames_spin.setValue(settings['max_frames'])
            
            # Load last video path
            last_video = settings.get('last_video_path')
            if last_video and Path(last_video).exists():
                self.video_path = last_video
                self.video_path_label.setText(f"Video: {Path(last_video).name}")
                self._log(f"Loaded video: {last_video}")
                self._load_video_preview(last_video)
                
                # Load video info
                try:
                    processor = VideoProcessor()
                    info = processor.get_video_info(last_video)
                    self.video_info_label.setText(
                        f"Resolution: {info['width']}x{info['height']} | "
                        f"FPS: {info['fps']:.2f} | "
                        f"Frames: {info['frame_count']} | "
                        f"Duration: {info['duration']:.2f}s"
                    )
                except Exception as e:
                    self._log(f"⚠ Error loading video info: {e}")
                    self.video_info_label.setText(f"Video info: Error - {e}")
            
            self._log("✓ Settings loaded")
        
        except Exception as e:
            self._log(f"⚠ Could not load settings: {e}")
    
    def _save_settings(self):
        """Save settings to file"""
        try:
            settings = {
                'last_video_path': self.video_path,
                'reconstruction_method': self.method_combo.currentIndex(),
                'training_iterations': self.iterations_spin.value(),
                'sample_rate': self.sample_rate_spin.value(),
                'max_frames': self.max_frames_spin.value(),
            }
            
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        
        except Exception as e:
            self._log(f"⚠ Could not save settings: {e}")
    
    def _load_ply_in_viewer(self, ply_path: str):
        """Load PLY file in the 3D viewer"""
        try:
            ply_path = Path(ply_path).resolve()
            if not ply_path.exists():
                self._log(f"⚠ PLY file not found: {ply_path}")
                return
            
            # Convert to file:// URL with query parameter
            viewer_html = Path(__file__).parent / "viewer" / "viewer.html"
            url = QUrl.fromLocalFile(str(viewer_html))
            url.setQuery(f"ply=file://{ply_path}")
            
            self.viewer.setUrl(url)
            self.tabs.setCurrentIndex(2)  # Switch to 3D Viewer tab
            self._log(f"✓ Loaded PLY in viewer: {ply_path.name}")
            
        except Exception as e:
            self._log(f"⚠ Error loading PLY in viewer: {e}")
            import traceback
            traceback.print_exc()

    # ── Video Preview ──────────────────────────────────────────────────────────

    def _on_tab_changed(self, index: int):
        """Pause video when leaving the Video Preview tab"""
        if index != 1:  # 1 = Video Preview tab
            self.media_player.pause()

    def _load_video_preview(self, video_path: str):
        """Load video into the preview player"""
        self.media_player.setSource(QUrl.fromLocalFile(video_path))

    def _on_play_pause(self):
        """Toggle play/pause"""
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            if not self.media_player.source().isEmpty():
                self.media_player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        """Update play button text based on actual playback state"""
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("Pause")
        else:
            self.play_btn.setText("Play")

    def _on_video_seek(self, position: int):
        """Seek video to slider position"""
        self.media_player.setPosition(position)

    def _on_video_position_changed(self, position: int):
        """Update slider and time label on playback"""
        self.video_slider.setValue(position)
        self.video_time_label.setText(
            f"{self._fmt_ms(position)} / {self._fmt_ms(self.media_player.duration())}"
        )

    def _on_video_duration_changed(self, duration: int):
        """Set slider range when video loads"""
        self.video_slider.setRange(0, duration)

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        """Format milliseconds as m:ss"""
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

