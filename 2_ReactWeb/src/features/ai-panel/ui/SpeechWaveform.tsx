import { useEffect, useRef } from "react";

const BAR_COUNT = 29;

/** Observe the existing microphone stream; never acquire or stop its tracks. */
export function SpeechWaveform({ stream }: { stream?: MediaStream }) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!stream || !root || typeof AudioContext === "undefined") return;
    let context: AudioContext | undefined;
    let source: MediaStreamAudioSourceNode | undefined;
    let frame = 0;
    let stopped = false;
    const bars = Array.from(root.children) as HTMLElement[];
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const reset = () => bars.forEach((bar) => {
      bar.style.removeProperty("transform");
      bar.style.removeProperty("opacity");
    });

    try {
      context = new AudioContext();
      source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.78;
      source.connect(analyser); // No destination: microphone must never play back.
      const samples = new Uint8Array(analyser.frequencyBinCount);
      let lastPaint = 0;
      const draw = (time: number) => {
        if (stopped) return;
        frame = requestAnimationFrame(draw);
        if (document.hidden || time - lastPaint < (reducedMotion.matches ? 200 : 33)) return;
        lastPaint = time;
        analyser.getByteFrequencyData(samples);
        bars.forEach((bar, index) => {
          const distance = Math.abs(index - (BAR_COUNT - 1) / 2);
          // Mirror the speech spectrum: stronger low frequencies at the centre.
          const bin = 1 + Math.floor(distance * 3);
          const strength = (samples[bin] + samples[bin + 1]) / 510;
          const envelope = 1 - distance / BAR_COUNT;
          bar.style.transform = `scaleY(${0.09 + Math.pow(strength, 1.5) * envelope * 0.91})`;
          bar.style.opacity = String(0.24 + strength * 0.76);
        });
      };
      frame = requestAnimationFrame(draw);
      void context.resume().catch(() => { /* Visualisation is optional; recording continues. */ });
    } catch {
      reset(); // Unsupported audio analysis must not prevent recording.
    }

    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      source?.disconnect();
      if (context && context.state !== "closed") void context.close().catch(() => {});
      reset();
    };
  }, [stream]);

  return <div ref={rootRef} className="ai-panel__speech-waveform" aria-hidden="true">
    {Array.from({ length: BAR_COUNT }, (_, index) => <span key={index} />)}
  </div>;
}
