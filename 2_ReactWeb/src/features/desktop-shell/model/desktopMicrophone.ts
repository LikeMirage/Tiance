/** The native host defers its real permission request until the composer answers. */
export type MicrophonePermissionAnswer = (allow: boolean) => Promise<void>;
type PermissionWindow = Window & {
  __tianceMicrophonePermissionRequest?: (requestId: string) => boolean;
};

// One permission request per window, even when switching between composers.
let pendingAcquisition: Promise<unknown> = Promise.resolve();

export function openSpeechMicrophone(signal: AbortSignal,
  onPermission: (answer: MicrophonePermissionAnswer) => void): Promise<MediaStream> {
  const host = window as PermissionWindow;
  const respond = host.pywebview?.api?.respond_microphone_permission;
  if (!respond) return navigator.mediaDevices.getUserMedia({ audio: true });

  const acquire = async () => {
    signal.throwIfAborted();
    let requestId: string | undefined;
    let answered = false;
    const answer: MicrophonePermissionAnswer = async (allow) => {
      if (!requestId || answered) return;
      answered = true;
      try {
        const accepted = await respond(requestId, allow && !signal.aborted);
        if (!accepted && !signal.aborted) throw new Error("麦克风授权请求已失效，请重试。");
      } catch (error) {
        answered = false;
        throw error;
      }
    };
    const deny = () => { void answer(false).catch(() => { /* A closed host also revokes its pending requests. */ }); };
    const handler = (id: string) => {
      requestId = id;
      if (signal.aborted) deny();
      else onPermission(answer);
      return true;
    };
    host.__tianceMicrophonePermissionRequest = handler;
    signal.addEventListener("abort", deny, { once: true });
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: true });
    } finally {
      signal.removeEventListener("abort", deny);
      if (host.__tianceMicrophonePermissionRequest === handler) delete host.__tianceMicrophonePermissionRequest;
    }
  };
  const result = pendingAcquisition.then(acquire, acquire);
  pendingAcquisition = result.catch(() => {});
  return result;
}
