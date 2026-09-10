"""Video frame extraction utilities for Stage 10 live investigation recording."""
import cv2
import os
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class FrameMetadata:
    width: int
    height: int
    fps: float
    total_frames: int
    duration_seconds: float


class VideoFrameError(Exception):
    """Error during video frame extraction."""
    pass


def get_video_metadata(video_path: str) -> FrameMetadata:
    """Extract metadata from video file."""
    if not os.path.exists(video_path):
        raise VideoFrameError(f"Video file not found: {video_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise VideoFrameError(f"Cannot open video file: {video_path}")
    
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        return FrameMetadata(
            width=width,
            height=height,
            fps=fps,
            total_frames=total_frames,
            duration_seconds=duration
        )
    finally:
        cap.release()


def extract_frame_at_timestamp(video_path: str, timestamp_seconds: float) -> tuple[bytes, dict]:
    """Extract a single frame at the given timestamp."""
    if not os.path.exists(video_path):
        raise VideoFrameError(f"Video file not found: {video_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise VideoFrameError(f"Cannot open video file: {video_path}")
    
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            raise VideoFrameError("Invalid video FPS")
        
        frame_number = int(timestamp_seconds * fps)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if frame_number >= total_frames:
            frame_number = max(0, total_frames - 1)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        
        if not ret or frame is None:
            raise VideoFrameError(f"Failed to read frame at {timestamp_seconds}s")
        
        # Encode as JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_bytes = buffer.tobytes()
        
        metadata = {
            "width": frame.shape[1],
            "height": frame.shape[0],
            "channels": frame.shape[2] if len(frame.shape) > 2 else 1,
        }
        
        return frame_bytes, metadata
    finally:
        cap.release()


def extract_keyframes(video_path: str, interval_seconds: float = 10.0, 
                      max_frames: int = 100) -> list[tuple[float, bytes, dict]]:
    """Extract keyframes at regular intervals."""
    if not os.path.exists(video_path):
        raise VideoFrameError(f"Video file not found: {video_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise VideoFrameError(f"Cannot open video file: {video_path}")
    
    frames = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            raise VideoFrameError("Invalid video FPS")
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        frame_interval = int(interval_seconds * fps)
        if frame_interval <= 0:
            frame_interval = 1
        
        frame_count = 0
        extracted = 0
        
        while extracted < max_frames:
            frame_number = frame_count * frame_interval
            if frame_number >= total_frames:
                break
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            
            if not ret or frame is None:
                break
            
            timestamp = frame_number / fps
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_bytes = buffer.tobytes()
            
            metadata = {
                "width": frame.shape[1],
                "height": frame.shape[0],
                "channels": frame.shape[2] if len(frame.shape) > 2 else 1,
            }
            
            frames.append((timestamp, frame_bytes, {
                "width": frame.shape[1],
                "height": frame.shape[0],
                "channels": frame.shape[2] if len(frame.shape) > 2 else 1,
            }))
            
            extracted += 1
            frame_count += 1
            
        return frames
    finally:
        cap.release()


def extract_frames_for_ai_analysis(video_path: str, timestamps: list[float]) -> list[tuple[float, bytes, dict]]:
    """Extract frames at specific timestamps for AI analysis."""
    if not os.path.exists(video_path):
        raise VideoFrameError(f"Video file not found: {video_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise VideoFrameError(f"Cannot open video file: {video_path}")
    
    frames = []
    try:
        for timestamp in timestamps:
            frame_bytes, metadata = extract_frame_at_timestamp(video_path, timestamp)
            frames.append((timestamp, frame_bytes, metadata))
        return frames
    finally:
        pass  # cap released in extract_frame_at_timestamp


def get_video_info(video_path: str) -> dict:
    """Get comprehensive video information."""
    metadata = get_video_metadata(video_path)
    return {
        "width": metadata.width,
        "height": metadata.height,
        "fps": metadata.fps,
        "total_frames": metadata.total_frames,
        "duration_seconds": metadata.duration_seconds,
        "duration_formatted": format_duration(metadata.duration_seconds),
    }


def format_duration(seconds: float) -> str:
    """Format duration as HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def validate_video_file(video_path: str) -> tuple[bool, str]:
    """Validate video file is readable and has valid format."""
    if not os.path.exists(video_path):
        return False, "File not found"
    
    if os.path.getsize(video_path) == 0:
        return False, "File is empty"
    
    try:
        metadata = get_video_metadata(video_path)
        if metadata.total_frames == 0:
            return False, "No frames in video"
        if metadata.duration_seconds <= 0:
            return False, "Invalid duration"
        return True, "OK"
    except Exception as e:
        return False, str(e)