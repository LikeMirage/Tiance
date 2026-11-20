import { Microphone, Stop, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { SpeechInputState } from "../model/useSpeechInput";
import { SpeechWaveform } from "./SpeechWaveform";
import "./styles/chat-speech.css";

export function ChatSpeechRecording({ speech }: { speech: SpeechInputState }) {
  const [now, setNow] = useState(Date.now());
  const view = speech.view;
  useEffect(() => {
    if (view?.phase !== "recording") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [view?.phase]);
  if (!view) return null;
  const recording = view.phase === "recording";
  const seconds = Math.max(0, Math.floor((now - view.startedAt) / 1000));
  return <div className="ai-panel__speech" aria-live="polite">
    {view.phase === "permission" ? <>
      <Microphone size={28} className="ai-panel__speech-permission-icon" aria-hidden="true" />
      <span className="ai-panel__speech-permission-title">使用麦克风录入文字</span>
      <div className="ai-panel__speech-permission-actions">
        <button type="button" className="ai-panel__speech-allow" onClick={speech.allowMicrophone}>允许使用麦克风</button>
        <button type="button" className="ai-panel__speech-cancel" onClick={speech.cancel}>取消</button>
      </div>
    </> : recording ? <div className="ai-panel__speech-recording">
      <div className="ai-panel__speech-orbit">
        <span className="ai-panel__speech-halo" aria-hidden="true" />
        <span className="ai-panel__speech-ripple" aria-hidden="true" />
        <span className="ai-panel__speech-ripple ai-panel__speech-ripple--delayed" aria-hidden="true" />
        <button type="button" className="ai-panel__speech-stop" onClick={speech.stop} aria-label="结束录音并识别" title="结束录音并识别">
          <Stop size={26} weight="fill" aria-hidden="true" />
        </button>
      </div>
      <span className="ai-panel__speech-label">正在录音 <span className="ai-panel__speech-dot">·</span> <span className="ai-panel__speech-time">{Math.floor(seconds / 60).toString().padStart(2, "0")}:{(seconds % 60).toString().padStart(2, "0")}</span></span>
      <SpeechWaveform stream={view.stream} />
    </div> : view.phase === "error" ? <span role="alert" className="ai-panel__speech-error">{view.error}</span> : (
      <div className={`ai-panel__speech-processing${view.phase === "cancelling" ? " ai-panel__speech-processing--cancelling" : ""}`}>
        <div className="ai-panel__speech-processing-visual" aria-hidden="true">
          <span className="ai-panel__speech-processing-glow" />
          <span className="ai-panel__speech-processing-ring" />
          <div className="ai-panel__speech-processing-core">
            {view.phase === "starting" ? <Microphone size={25} weight="light" /> : (
              <div className="ai-panel__speech-processing-wave"><i /><i /><i /><i /><i /></div>
            )}
          </div>
        </div>
        <div className="ai-panel__speech-processing-copy">
          <span className="ai-panel__speech-processing-title">
            {view.phase === "starting" ? "正在打开麦克风" : view.phase === "cancelling" ? "正在取消" : "正在识别"}
          </span>
          <span className="ai-panel__speech-processing-description">
            {view.phase === "starting" ? "准备好后即可开始说话" : view.phase === "cancelling" ? "本次结果不会写入输入框" : "将语音转为文字，完成后填入输入框"}
          </span>
        </div>
        <button type="button" className="ai-panel__speech-processing-cancel" onClick={speech.cancel} disabled={view.phase === "cancelling"}>
          <X size={12} aria-hidden="true" />
          {view.phase === "cancelling" ? "取消中" : view.phase === "starting" ? "取消" : "取消识别"}
        </button>
      </div>
    )}
    {view.phase === "error" && <button type="button" className="ai-panel__speech-cancel" onClick={speech.cancel}>返回输入</button>}
  </div>;
}
