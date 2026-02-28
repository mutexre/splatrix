import { useRef, useState, useEffect, useCallback } from 'react';
import { Play, Pause, Volume2, VolumeX, Maximize } from 'lucide-react';

interface Props {
  videoUrl: string | null;
  isActiveTab: boolean;
}

export function VideoTab({ videoUrl, isActiveTab }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Pause when tab is not active
  useEffect(() => {
    if (!isActiveTab && videoRef.current && isPlaying) {
      videoRef.current.pause();
    }
  }, [isActiveTab, isPlaying]);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); } else { v.pause(); }
  }, []);

  const handleSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = +e.target.value;
  }, []);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  if (!videoUrl) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <div className="text-center">
          <div className="text-4xl mb-3 opacity-30">🎬</div>
          <p>No video loaded</p>
          <p className="text-xs mt-1 opacity-60">Select a video in the Pipeline tab</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-black">
      {/* Video */}
      <div className="flex-1 flex items-center justify-center min-h-0">
        <video
          ref={videoRef}
          src={videoUrl}
          className="max-w-full max-h-full object-contain"
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime ?? 0)}
          onLoadedMetadata={() => setDuration(videoRef.current?.duration ?? 0)}
          onClick={togglePlay}
        />
      </div>

      {/* Controls */}
      <div className="bg-surface border-t border-border-subtle px-4 py-2 flex items-center gap-3">
        <button onClick={togglePlay} className="text-text hover:text-accent transition-colors">
          {isPlaying ? <Pause size={18} /> : <Play size={18} />}
        </button>

        <span className="text-xs text-text-muted w-20 text-right font-mono">
          {formatTime(currentTime)}
        </span>

        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={currentTime}
          onChange={handleSeek}
          className="flex-1 h-1 accent-accent cursor-pointer"
        />

        <span className="text-xs text-text-muted w-20 font-mono">
          {formatTime(duration)}
        </span>

        <button
          onClick={() => { setIsMuted(!isMuted); if (videoRef.current) videoRef.current.muted = !isMuted; }}
          className="text-text-muted hover:text-text transition-colors"
        >
          {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>

        <button
          onClick={() => videoRef.current?.requestFullscreen()}
          className="text-text-muted hover:text-text transition-colors"
        >
          <Maximize size={16} />
        </button>
      </div>
    </div>
  );
}
