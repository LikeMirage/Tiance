import type { MutableRefObject } from "react";

import type { ChatStreamEvent } from "../../../entities/llm-chat/model/chatCompletion";

export type ChatStreamEventSequenceState = {
  claimed: MutableRefObject<Set<string>>;
  processed: MutableRefObject<Map<string, number>>;
  queues: MutableRefObject<Map<string, Promise<void>>>;
};

export async function processSequencedChatStreamEvent(
  sessionKey: string,
  event: ChatStreamEvent,
  state: ChatStreamEventSequenceState,
  processEvent: () => void | Promise<void>,
) {
  const sequence = event.run_sequence;
  if (!sequence) {
    await processEvent();
    return;
  }

  const previous = state.queues.current.get(sessionKey) ?? Promise.resolve();
  const queued = previous
    .catch(() => undefined)
    .then(async () => {
      const claimKey = `${sessionKey}:${sequence}`;
      if ((state.processed.current.get(sessionKey) ?? 0) >= sequence) return;
      if (state.claimed.current.has(claimKey)) return;
      state.claimed.current.add(claimKey);
      try {
        await processEvent();
        state.processed.current.set(
          sessionKey,
          Math.max(state.processed.current.get(sessionKey) ?? 0, sequence),
        );
      } finally {
        state.claimed.current.delete(claimKey);
      }
    });
  state.queues.current.set(sessionKey, queued);
  try {
    await queued;
  } finally {
    if (state.queues.current.get(sessionKey) === queued) {
      state.queues.current.delete(sessionKey);
    }
  }
}

export function clearChatStreamEventSequence(
  sessionKey: string,
  state: ChatStreamEventSequenceState,
) {
  state.processed.current.delete(sessionKey);
  const prefix = `${sessionKey}:`;
  for (const claimKey of state.claimed.current) {
    if (claimKey.startsWith(prefix)) {
      state.claimed.current.delete(claimKey);
    }
  }
}
