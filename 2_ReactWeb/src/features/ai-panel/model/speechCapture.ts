import { conversationSpeech, speechEndpoint } from "../../../services/project/conversationSpeech";
import type { SpeechDraftOrigin } from "./speechDraft";
import { openSpeechMicrophone, type MicrophonePermissionAnswer } from "../../desktop-shell/model/desktopMicrophone";

export type SpeechPhase = "starting" | "permission" | "recording" | "recognizing" | "cancelling" | "error";
export type SpeechView = { phase: SpeechPhase; startedAt: number; error?: string; stream?: MediaStream };
type Capture = {
  origin: SpeechDraftOrigin;
  view: SpeechView;
  cancelled: boolean;
  stopped: boolean;
  recorder?: MediaRecorder;
  stream?: MediaStream;
  request: AbortController;
  path?: string;
  saved?: boolean;
  permission?: MicrophonePermissionAnswer;
};
const key = (project: string, session: string) => JSON.stringify([project, session]);

/** Owns each recording until delivery/cancellation, independent of which composer is visible. */
export class SpeechCapture {
  private captures = new Map<string, Capture>();
  private listeners = new Set<() => void>();
  constructor(
    private deliver: (origin: SpeechDraftOrigin, text: string) => void,
    private api = conversationSpeech,
    private media = openSpeechMicrophone,
    private makeRecorder = (stream: MediaStream) => {
      const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
        .find((type) => MediaRecorder.isTypeSupported(type));
      return new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    },
  ) {}

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private notify() { this.listeners.forEach((listener) => listener()); }
  get(project: string | null, session: string | null): SpeechView | null {
    return project && session ? this.captures.get(key(project, session))?.view ?? null : null;
  }
  private set(capture: Capture, phase: SpeechPhase, error?: string) {
    capture.view = { ...capture.view, phase, error, stream: phase === "recording" ? capture.stream : undefined };
    this.notify();
  }
  private remove(capture: Capture) {
    const id = key(capture.origin.projectId, capture.origin.sessionId);
    if (this.captures.get(id) === capture) this.captures.delete(id);
    this.notify();
  }
  private closeMicrophone(capture: Capture) {
    capture.stream?.getTracks().forEach((track) => track.stop());
  }

  async start(origin: SpeechDraftOrigin) {
    const id = key(origin.projectId, origin.sessionId);
    if (this.captures.has(id)) return;
    // Only one microphone capture; older recognitions may continue independently.
    this.leave(null, null);
    const capture: Capture = { origin, view: { phase: "starting", startedAt: Date.now() },
      cancelled: false, stopped: false, request: new AbortController() };
    this.captures.set(id, capture);
    this.notify();
    try {
      capture.stream = await this.media(capture.request.signal, (answer) => {
        if (capture.cancelled || capture.stopped) { void answer(false); return; }
        capture.permission = answer;
        this.set(capture, "permission");
      });
      if (capture.cancelled || capture.stopped) {
        this.closeMicrophone(capture);
        this.remove(capture);
        return;
      }
      const recorder = this.makeRecorder(capture.stream);
      capture.recorder = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => {
        capture.cancelled = true;
        this.closeMicrophone(capture);
        this.set(capture, "error", "录音失败，请检查麦克风权限和设备。 ");
      };
      recorder.onstop = () => {
        this.closeMicrophone(capture);
        if (capture.cancelled) return;
        void this.recognize(capture, new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || "audio/webm" }));
      };
      recorder.start(1000);
      capture.view.startedAt = Date.now();
      this.set(capture, "recording");
    } catch (error) {
      this.closeMicrophone(capture);
      if (capture.cancelled || capture.stopped) this.remove(capture);
      else this.set(capture, "error", error instanceof Error ? error.message : "无法使用麦克风。");
    }
  }

  stop(project: string, session: string) {
    const capture = this.captures.get(key(project, session));
    if (!capture || capture.stopped) return;
    capture.stopped = true;
    if (["starting", "permission"].includes(capture.view.phase)) {
      capture.request.abort();
      this.remove(capture);
      return;
    }
    if (capture.recorder?.state === "recording") {
      this.set(capture, "recognizing");
      capture.recorder.stop();
    }
  }

  leave(project: string | null, session: string | null) {
    for (const capture of this.captures.values()) {
      if (capture.origin.projectId !== project || capture.origin.sessionId !== session) {
        if (["starting", "permission", "recording"].includes(capture.view.phase)) {
          this.stop(capture.origin.projectId, capture.origin.sessionId);
        }
      }
    }
  }

  async allowMicrophone(project: string, session: string) {
    const capture = this.captures.get(key(project, session));
    if (!capture?.permission || capture.view.phase !== "permission") return;
    this.set(capture, "starting");
    try { await capture.permission(true); }
    catch (error) {
      if (!capture.cancelled && !capture.stopped) {
        this.set(capture, "error", error instanceof Error ? error.message : "麦克风授权失败，请重试。");
      }
    }
  }

  async cancel(project: string, session: string) {
    const capture = this.captures.get(key(project, session));
    if (!capture) return;
    capture.cancelled = true; // Must precede abort and asynchronous DELETE.
    capture.request.abort();
    this.set(capture, "cancelling");
    if (capture.recorder?.state === "recording") capture.recorder.stop();
    this.closeMicrophone(capture);
    try {
      if (capture.path && capture.saved) await this.api.cancel(capture.path);
      this.remove(capture);
    } catch {
      this.set(capture, "error", "未能确认后端停止，请重试取消。本次识别文字不会填入。 ");
    }
  }

  private async recognize(capture: Capture, blob: Blob) {
    this.set(capture, "recognizing");
    const { projectId, sessionId } = capture.origin;
    try {
      if (!blob.size) throw new Error("没有录到声音，请检查麦克风。");
      const base = speechEndpoint(projectId, sessionId);
      // Keep create alive so even a cancellation racing creation gets a job ID
      // that can be explicitly cancelled on the backend.
      const created = await this.api.create(base);
      capture.path = `${base}/${created.id}`;
      // Saving the finished recording is independent of recognition. Cancelling
      // while it is being saved must not leave a truncated source recording.
      await this.api.upload(capture.path, blob);
      capture.saved = true;
      if (capture.cancelled) { await this.api.cancel(capture.path); return; }
      await this.api.start(capture.path, capture.request.signal);
      while (!capture.cancelled) {
        const state = await this.api.status(capture.path, capture.request.signal);
        if (capture.cancelled) return;
        if (state.status === "completed") {
          if (state.text) this.deliver(capture.origin, state.text);
          else throw new Error("未识别到文字，录音已保留。 ");
          this.remove(capture);
          return;
        }
        if (state.status === "failed") throw new Error(state.error || "语音识别失败，录音已保留。 ");
        if (state.status === "cancelled") { this.remove(capture); return; }
        await new Promise((resolve) => setTimeout(resolve, 750));
      }
    } catch (error) {
      if (capture.cancelled) return;
      // A transport failure is not proof that server work stopped.
      if (capture.path) {
        try { await this.api.cancel(capture.path); }
        catch { /* Keep the job ID so the user can retry cancellation. */ }
      }
      this.set(capture, "error", error instanceof Error ? error.message : "语音识别失败，录音已保留。");
    }
  }
}
