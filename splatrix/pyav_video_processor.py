"""PyAV-based video processor implementation with direct frame control"""

from pathlib import Path
from typing import Optional, Callable, Dict
import shutil
import numpy as np
from PIL import Image

from .video_processing_base import BaseVideoProcessor, ProcessingConfig

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False

try:
    import pycolmap
    PYCOLMAP_AVAILABLE = True
except ImportError:
    PYCOLMAP_AVAILABLE = False


class PyAVVideoProcessor(BaseVideoProcessor):
    """
    Video processor using PyAV for direct frame extraction.
    Uses pycolmap Python API for Structure from Motion.
    Provides frame-by-frame progress tracking.
    """
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        super().__init__()
        
        if not PYAV_AVAILABLE:
            raise ImportError("PyAV not installed. Install with: pip install av")
        
        if not PYCOLMAP_AVAILABLE:
            raise ImportError("pycolmap not installed. Install with: pip install pycolmap")
        
        self.config = config or ProcessingConfig()
    
    def cancel(self) -> None:
        """Request cancellation"""
        self._is_cancelled = True
    
    def get_video_info(self, video_path: str) -> Dict[str, any]:
        """Get video metadata using PyAV"""
        try:
            container = av.open(video_path)
            video_stream = container.streams.video[0]
            
            width = video_stream.width
            height = video_stream.height
            fps = float(video_stream.average_rate)
            duration = float(video_stream.duration * video_stream.time_base) if video_stream.duration else 0
            frame_count = video_stream.frames
            
            # Estimate frame count if not available
            if frame_count == 0 and duration > 0:
                frame_count = int(duration * fps)
            
            container.close()
            
            return {
                'width': width,
                'height': height,
                'fps': fps,
                'frame_count': frame_count,
                'duration': duration
            }
        
        except Exception as e:
            raise RuntimeError(f"Failed to get video info: {e}")
    
    def _extract_frames(
        self,
        video_path: str,
        output_dir: Path,
        num_frames_target: int,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> int:
        """
        Extract frames from video using PyAV with frame-by-frame progress
        
        Returns:
            Number of frames extracted
        """
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        
        if progress_callback:
            progress_callback("Opening video", 0.01)
        
        container = av.open(video_path)
        video_stream = container.streams.video[0]
        
        # Calculate frame sampling
        total_frames = video_stream.frames
        if total_frames == 0:
            # Estimate from duration and fps
            fps = float(video_stream.average_rate)
            duration = float(video_stream.duration * video_stream.time_base) if video_stream.duration else 0
            total_frames = int(duration * fps)
        
        # Calculate which frames to keep
        if total_frames <= num_frames_target:
            frame_step = 1
        else:
            frame_step = total_frames / num_frames_target
        
        extracted_count = 0
        frame_index = 0
        next_extract = 0.0
        
        if progress_callback:
            progress_callback("Extracting frames: 0", 0.05)
        
        try:
            for frame in container.decode(video=0):
                if self._is_cancelled:
                    raise InterruptedError("Frame extraction cancelled")
                
                # Check if we should extract this frame
                if frame_index >= next_extract:
                    # Convert frame to numpy array
                    img_array = frame.to_ndarray(format='rgb24')
                    
                    # Save as PNG
                    img = Image.fromarray(img_array)
                    frame_filename = images_dir / f"frame_{extracted_count:05d}.png"
                    img.save(frame_filename)
                    
                    extracted_count += 1
                    next_extract += frame_step
                    
                    # Report progress
                    if progress_callback and extracted_count % 10 == 0:
                        progress = 0.05 + (extracted_count / num_frames_target) * 0.10
                        progress_callback(f"Extracting frames: {extracted_count}", min(progress, 0.15))
                    
                    # Stop if we have enough frames
                    if extracted_count >= num_frames_target:
                        break
                
                frame_index += 1
        
        finally:
            container.close()
        
        if progress_callback:
            progress_callback(f"Extracted {extracted_count} frames", 0.15)
        
        return extracted_count
    
    def _run_colmap_sfm(
        self,
        images_dir: Path,
        colmap_dir: Path,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> None:
        """
        Run Structure from Motion using pycolmap Python API
        """
        database_path = colmap_dir / "database.db"
        sparse_dir = colmap_dir / "sparse" / "0"
        sparse_dir.mkdir(parents=True, exist_ok=True)
        
        if progress_callback:
            progress_callback("Initializing COLMAP", 0.16)
        
        # Feature extraction
        if progress_callback:
            progress_callback("COLMAP: Extracting features", 0.20)
        
        try:
            # Get camera mode enum
            from pycolmap import CameraMode
            camera_mode = CameraMode.SINGLE
        except (ImportError, AttributeError):
            camera_mode = "SINGLE"
        
        # Extract features with progress tracking
        image_list = sorted(images_dir.glob("*.png"))
        total_images = len(image_list)
        
        try:
            pycolmap.extract_features(
                database_path=str(database_path),
                image_path=str(images_dir),
                camera_mode=camera_mode,
                sift_options={
                    'max_num_features': 8192,
                }
            )
            
            if progress_callback:
                progress_callback(f"COLMAP: Features extracted [{total_images} images]", 0.30)
        
        except Exception as e:
            raise RuntimeError(f"Feature extraction failed: {e}")
        
        if self._is_cancelled:
            raise InterruptedError("COLMAP cancelled")
        
        # Feature matching
        if progress_callback:
            progress_callback("COLMAP: Matching features", 0.35)
        
        try:
            if self.config.matcher_type == "exhaustive":
                pycolmap.match_exhaustive(str(database_path))
            elif self.config.matcher_type == "sequential":
                pycolmap.match_sequential(str(database_path), sequential_overlap=10)
            elif self.config.matcher_type == "vocab_tree":
                pycolmap.match_vocab_tree(str(database_path))
            else:
                pycolmap.match_sequential(str(database_path))
            
            if progress_callback:
                progress_callback("COLMAP: Matching complete", 0.50)
        
        except Exception as e:
            raise RuntimeError(f"Feature matching failed: {e}")
        
        if self._is_cancelled:
            raise InterruptedError("COLMAP cancelled")
        
        # Sparse reconstruction (incremental mapping)
        if progress_callback:
            progress_callback("COLMAP: Building sparse reconstruction", 0.55)
        
        try:
            # Incremental mapping
            maps = pycolmap.incremental_mapping(
                database_path=str(database_path),
                image_path=str(images_dir),
                output_path=str(sparse_dir.parent),
                options={
                    'min_num_matches': 15,
                    'num_threads': -1,  # Use all available threads
                }
            )
            
            if not maps or len(maps) == 0:
                raise RuntimeError("Reconstruction failed - no 3D points generated")
            
            # Save the best (largest) reconstruction
            best_map = max(maps.items(), key=lambda x: len(x[1].points3D))[1]
            best_map.write(str(sparse_dir))
            
            num_registered = len(best_map.images)
            num_points = len(best_map.points3D)
            
            if progress_callback:
                progress_callback(
                    f"COLMAP: Reconstruction complete [{num_registered} images, {num_points} points]",
                    0.80
                )
        
        except Exception as e:
            raise RuntimeError(f"Sparse reconstruction failed: {e}")
        
        if progress_callback:
            progress_callback("COLMAP processing complete", 0.95)
    
    def _create_transforms_json(
        self,
        colmap_dir: Path,
        images_dir: Path,
        output_path: Path
    ) -> None:
        """
        Create transforms.json from COLMAP sparse reconstruction
        (nerfstudio format)
        """
        import json
        
        sparse_dir = colmap_dir / "sparse" / "0"
        
        # Read COLMAP reconstruction
        reconstruction = pycolmap.Reconstruction(str(sparse_dir))
        
        if len(reconstruction.cameras) == 0:
            raise RuntimeError("No cameras in reconstruction")
        
        # Get camera (assume single camera)
        camera_id = list(reconstruction.cameras.keys())[0]
        camera = reconstruction.cameras[camera_id]
        
        transforms = {
            "camera_model": camera.model_name,
            "fl_x": camera.params[0] if len(camera.params) > 0 else camera.focal_length,
            "fl_y": camera.params[1] if len(camera.params) > 1 else camera.focal_length,
            "cx": camera.params[2] if len(camera.params) > 2 else camera.width / 2,
            "cy": camera.params[3] if len(camera.params) > 3 else camera.height / 2,
            "w": camera.width,
            "h": camera.height,
            "frames": []
        }
        
        # Add frames
        for image_id, image in reconstruction.images.items():
            # Get rotation and translation
            quat = image.qvec  # Quaternion (w, x, y, z)
            tvec = image.tvec  # Translation
            
            # Convert to 4x4 transform matrix
            # (nerfstudio expects world-to-camera)
            from scipy.spatial.transform import Rotation
            R = Rotation.from_quat([quat[1], quat[2], quat[3], quat[0]]).as_matrix()
            
            transform_matrix = np.eye(4)
            transform_matrix[:3, :3] = R
            transform_matrix[:3, 3] = tvec
            
            frame_data = {
                "file_path": f"images/{image.name}",
                "transform_matrix": transform_matrix.tolist()
            }
            
            transforms["frames"].append(frame_data)
        
        # Write transforms.json
        with open(output_path, 'w') as f:
            json.dump(transforms, f, indent=2)
    
    def process_video(
        self,
        video_path: str,
        output_dir: Path,
        num_frames_target: int = 300,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict[str, any]:
        """Process video using PyAV + pycolmap pipeline"""
        
        # Clean workspace
        images_dir = output_dir / "images"
        colmap_dir = output_dir / "colmap"
        
        if images_dir.exists():
            shutil.rmtree(images_dir)
        if colmap_dir.exists():
            shutil.rmtree(colmap_dir)
        
        images_dir.mkdir(parents=True)
        colmap_dir.mkdir(parents=True)
        
        # Step 1: Extract frames with PyAV
        frame_count = self._extract_frames(
            video_path,
            output_dir,
            num_frames_target,
            progress_callback
        )
        
        if self._is_cancelled:
            raise InterruptedError("Processing cancelled")
        
        # Step 2: Run COLMAP SfM
        self._run_colmap_sfm(
            images_dir,
            colmap_dir,
            progress_callback
        )
        
        if self._is_cancelled:
            raise InterruptedError("Processing cancelled")
        
        # Step 3: Create transforms.json
        if progress_callback:
            progress_callback("Creating transforms.json", 0.96)
        
        transforms_path = output_dir / "transforms.json"
        self._create_transforms_json(colmap_dir, images_dir, transforms_path)
        
        if progress_callback:
            progress_callback("Video processing complete", 1.0)
        
        return {
            'data_dir': str(output_dir),
            'transforms_path': str(transforms_path) if transforms_path.exists() else None,
            'images_dir': str(images_dir),
            'frame_count': frame_count
        }

