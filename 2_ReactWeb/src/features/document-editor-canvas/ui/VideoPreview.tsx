import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  CornersOut,
  FilmSlate,
  Pause,
  Play,
  SpeakerHigh,
  SpeakerSlash,
} from "@phosphor-icons/react";

import { RangeSlider } from "../../../shared/ui/range-slider";
import "./video-preview.css";

type VideoPreviewProps = {
  displayPath: string;
  fileName: string;
  src: string | null;
};

const playbackRates = [0.5, 1, 1.25, 1.5, 2];

export function VideoPreview({ displayPath, fileName, src }: VideoPreviewProps) {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [hasPlaybackError, setHasPlaybackError] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [volume, setVolume] = useState(1);
  const canPlay = Boolean(src) && !hasPlaybackError;
  const progressValue = duration > 0 ? currentTime : 0;

  useEffect(() => {
    setCurrentTime(0);
    setDuration(0);
    setHasPlaybackError(false);
    setIsPlaying(false);
    setPlaybackRate(1);
    const video = videoRef.current;
    if (video) {
      try {
        video.currentTime = 0;
      } catch {
        // Some browsers reject currentTime updates before metadata is ready.
      }
      video.playbackRate = 1;
    }
  }, [displayPath, src]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === shellRef.current);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const syncVideoState = () => {
    const video = videoRef.current;
    if (!video) return;
    setCurrentTime(video.currentTime || 0);
    setDuration(Number.isFinite(video.duration) ? video.duration : 0);
    setIsMuted(video.muted);
    setIsPlaying(!video.paused);
    setPlaybackRate(video.playbackRate);
    setVolume(video.volume);
  };

  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play().catch(() => setHasPlaybackError(true));
      return;
    }
    video.pause();
  };

  const seekTo = (nextTime: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Number.isFinite(nextTime) ? nextTime : 0;
    setCurrentTime(video.currentTime);
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setIsMuted(video.muted);
  };

  const changeVolume = (value: number) => {
    const video = videoRef.current;
    if (!video) return;
    const nextVolume = Math.max(0, Math.min(1, value));
    video.volume = Number.isFinite(nextVolume) ? nextVolume : 1;
    video.muted = video.volume === 0;
    syncVideoState();
  };

  const cyclePlaybackRate = () => {
    const video = videoRef.current;
    if (!video) return;
    const currentIndex = playbackRates.indexOf(playbackRate);
    const nextRate = playbackRates[(currentIndex + 1) % playbackRates.length] ?? 1;
    video.playbackRate = nextRate;
    setPlaybackRate(nextRate);
  };

  const toggleFullscreen = () => {
    const shell = shellRef.current;
    if (!shell) return;
    if (document.fullscreenElement === shell) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    void shell.requestFullscreen().catch(() => undefined);
  };

  const seekBy = (seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    const nextTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + seconds));
    video.currentTime = Number.isFinite(nextTime) ? nextTime : 0;
    setCurrentTime(video.currentTime);
  };

  const handlePlayerKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target instanceof HTMLButtonElement || event.target instanceof HTMLInputElement) {
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      seekBy(-5);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      seekBy(5);
      return;
    }
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      togglePlay();
      return;
    }
    if (event.key.toLowerCase() === "m") {
      event.preventDefault();
      toggleMute();
      return;
    }
    if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      toggleFullscreen();
    }
  };

  return (
    <div className="video-preview">
      <div className="video-preview__toolbar">
        <div className="video-preview__meta">
          <span className="video-preview__name">{fileName}</span>
          <span className="video-preview__path" title={displayPath}>{displayPath}</span>
        </div>
      </div>
      <div className="video-preview__viewport">
        {canPlay ? (
          <div
            className="video-preview__player-shell"
            ref={shellRef}
            tabIndex={0}
            onContextMenu={(event) => event.preventDefault()}
            onKeyDown={handlePlayerKeyDown}
            onPointerDown={(event) => {
              if (event.target === event.currentTarget || event.target === videoRef.current) {
                event.currentTarget.focus({ preventScroll: true });
              }
            }}
          >
            <video
              className="video-preview__player"
              controls={false}
              controlsList="nodownload noremoteplayback"
              disablePictureInPicture
              playsInline
              preload="metadata"
              ref={videoRef}
              src={src ?? undefined}
              onClick={togglePlay}
              onDurationChange={syncVideoState}
              onEnded={syncVideoState}
              onError={() => setHasPlaybackError(true)}
              onLoadedMetadata={syncVideoState}
              onPause={syncVideoState}
              onPlay={syncVideoState}
              onRateChange={syncVideoState}
              onTimeUpdate={syncVideoState}
              onVolumeChange={syncVideoState}
            >
              当前环境无法播放此视频。
            </video>
            <div className="video-preview__controls">
              <button
                className="video-preview__control-button"
                title={isPlaying ? "暂停" : "播放"}
                type="button"
                onClick={togglePlay}
              >
                {isPlaying ? <Pause size={15} weight="fill" /> : <Play size={15} weight="fill" />}
              </button>
              <span className="video-preview__time">{formatTime(currentTime)}</span>
              <RangeSlider
                ariaLabel="播放进度"
                className="video-preview__range video-preview__range--progress"
                max={duration || 0}
                min={0}
                step={0.1}
                value={progressValue}
                onValueChange={seekTo}
              />
              <span className="video-preview__time">{formatTime(duration)}</span>
              <button
                className="video-preview__control-button"
                title={isMuted ? "取消静音" : "静音"}
                type="button"
                onClick={toggleMute}
              >
                {isMuted || volume === 0
                  ? <SpeakerSlash size={16} weight="bold" />
                  : <SpeakerHigh size={16} weight="bold" />}
              </button>
              <RangeSlider
                ariaLabel="音量"
                className="video-preview__range video-preview__range--volume"
                max={1}
                min={0}
                step={0.01}
                value={isMuted ? 0 : volume}
                onValueChange={changeVolume}
              />
              <button
                className="video-preview__rate-button"
                title="播放速度"
                type="button"
                onClick={cyclePlaybackRate}
              >
                {formatPlaybackRate(playbackRate)}
              </button>
              <button
                className="video-preview__control-button"
                title={isFullscreen ? "退出全屏" : "全屏"}
                type="button"
                onClick={toggleFullscreen}
              >
                <CornersOut size={16} weight="bold" />
              </button>
            </div>
          </div>
        ) : (
          <div className="video-preview__error" role="status">
            <FilmSlate size={28} weight="duotone" />
            <span>视频无法播放</span>
          </div>
        )}
      </div>
    </div>
  );
}

function formatPlaybackRate(rate: number) {
  return `${Number.isInteger(rate) ? rate.toFixed(0) : rate}x`;
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "00:00";
  }
  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours > 0) {
    return `${padTime(hours)}:${padTime(minutes)}:${padTime(remainingSeconds)}`;
  }
  return `${padTime(minutes)}:${padTime(remainingSeconds)}`;
}

function padTime(value: number) {
  return value.toString().padStart(2, "0");
}
