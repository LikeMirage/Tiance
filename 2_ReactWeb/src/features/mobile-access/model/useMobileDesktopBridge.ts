import { useEffect, useRef, type MutableRefObject } from "react";
import type { ChatClientCapability, ChatCompletionMessageInput, ChatStreamEvent } from "../../../entities/llm-chat/model/chatCompletion";
import type { ClientToolExecutor } from "../../client-tools/model/clientToolBridge";
import { buildConversationRunRequest } from "../../conversation-runtime/model/conversationRunRequest";
import { processChatStreamEventSideEffects } from "../../conversation-runtime/model/chatStreamEventSideEffects";
import { getProjectConversationDetail } from "../../../services/project/getProjectConversationDetail";
import { fetchJson } from "../../../services/http/httpClient";

type Preparation = {
  id: string; project_id: string; session_id: string; user_message_id: string;
  content: string; references: ChatCompletionMessageInput["references"];
};

// This transport only prepares the same request as the desktop send action and
// services existing client capabilities. It never selects a project or edits a draft.
export function useMobileDesktopBridge(
  executor: MutableRefObject<ClientToolExecutor | null>,
  capabilities: MutableRefObject<readonly ChatClientCapability[]>,
) {
  const owner = useRef(crypto.randomUUID());
  useEffect(() => {
    const abort = new AbortController();
    let cursor = 0;
    const pending = new Set<string>();
    const prepare = async (job: Preparation) => {
      if (pending.has(job.id)) return;
      pending.add(job.id);
      let payload: unknown;
      let error: string | undefined;
      try {
        const { session } = await getProjectConversationDetail(job.project_id, job.session_id, abort.signal);
        if (!session.model_id || !session.provider_id || !session.settings) {
          throw new Error("目标会话尚未配置模型，请在天策中选择角色或模型后重发。");
        }
        payload = buildConversationRunRequest({
          messages: [{ role: "user", message_id: job.user_message_id, content: job.content, references: job.references }],
          modelId: session.model_id, providerId: session.provider_id, settings: session.settings,
          reasoningMode: session.reasoning_mode, projectId: job.project_id, sessionId: job.session_id,
          clientCapabilities: capabilities.current,
        });
      } catch (cause) {
        if (abort.signal.aborted) return;
        error = cause instanceof Error ? cause.message : String(cause);
      }
      try {
        await fetchJson(`/api/mobile/desktop/${job.id}/prepare`, {
          method: "POST", signal: abort.signal,
          body: JSON.stringify({ owner: owner.current, payload, error }),
        });
      } finally {
        pending.delete(job.id); // Transport failures may retry preparation; backend starts once.
      }
    };
    const run = async () => {
      while (!abort.signal.aborted) {
        try {
          const data = await fetchJson<{ preparations: Preparation[]; events: ChatStreamEvent[]; cursor?: number }>(
            `/api/mobile/desktop/poll?owner=${encodeURIComponent(owner.current)}&after=${cursor}`, { signal: abort.signal },
          );
          for (const job of data.preparations) void prepare(job).catch(() => undefined);
          for (const event of data.events) void processChatStreamEventSideEffects(event, executor.current);
          cursor = data.cursor ?? 0;
        } catch {
          // No task is restarted here. The backend owns execution and outcome delivery.
        }
        await new Promise<void>((resolve) => {
          if (abort.signal.aborted) { resolve(); return; }
          const done = () => { clearTimeout(timer); abort.signal.removeEventListener("abort", done); resolve(); };
          const timer = setTimeout(done, 1000);
          abort.signal.addEventListener("abort", done, { once: true });
        });
      }
    };
    void run();
    return () => {
      abort.abort();
      void fetchJson("/api/mobile/desktop/release", { method: "POST", keepalive: true,
        body: JSON.stringify({ owner: owner.current }),
      }).catch(() => undefined);
    };
  }, [capabilities, executor]);
}
