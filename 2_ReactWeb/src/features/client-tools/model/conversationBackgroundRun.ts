import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import { buildConversationRunRequest } from "../../ai-panel/model/conversationRunRequest";
import { processChatStreamEventSideEffects } from "../../ai-panel/model/chatStreamEventSideEffects";
import type { ClientToolExecutor } from "./clientToolBridge";
import {
  loadConversationTurnByUserMessageId,
} from "./loadConversationMessageTurns";
import type { ConversationTurn } from "./conversationMessageTurns";
import {
  followConversationRun,
  type ConversationRunInitialStrategy,
  type ConversationRunOutcome,
  type ConversationRunSettlement,
} from "./conversationRunFollower";

export type ConversationBackgroundRunResult = {
  assistantMessageId: string | null;
  outcome: ConversationRunOutcome;
  turn: ConversationTurn;
  userMessageId: string;
};

export type ConversationBackgroundRunStarted = {
  running: boolean;
  userMessageId: string;
};

export type ConversationBackgroundRunHandle = {
  completion: Promise<ConversationBackgroundRunResult>;
  started: Promise<ConversationBackgroundRunStarted>;
};

type ConversationBackgroundRunDependencies = {
  followRun: typeof followConversationRun;
  loadTurn: typeof loadConversationTurnByUserMessageId;
};

type ConversationBackgroundRunInput = {
  clientToolExecutor: () => ClientToolExecutor | null;
  initialStrategy?: ConversationRunInitialStrategy;
  message: string;
  onSettled?: (outcome: ConversationRunOutcome | null) => void | Promise<void>;
  onStarted?: () => void | Promise<void>;
  projectId: string;
  session: ConversationSession;
  userMessageId?: string;
};

type TrackedConversationRun = {
  handle: ConversationBackgroundRunHandle;
  userMessageId: string;
};

export class ConversationBackgroundRunRegistry {
  private readonly runs = new Map<string, TrackedConversationRun>();
  private readonly dependencies: ConversationBackgroundRunDependencies;

  constructor(dependencies: Partial<ConversationBackgroundRunDependencies> = {}) {
    this.dependencies = {
      followRun: dependencies.followRun ?? followConversationRun,
      loadTurn: dependencies.loadTurn ?? loadConversationTurnByUserMessageId,
    };
  }

  startOrResume(input: ConversationBackgroundRunInput): ConversationBackgroundRunHandle {
    const key = `${input.projectId}:${input.session.session_id}`;
    const userMessageId = input.userMessageId ?? crypto.randomUUID();
    const trackedRun = this.runs.get(key);
    if (trackedRun?.userMessageId === userMessageId) {
      return trackedRun.handle;
    }
    if (trackedRun) {
      throw new Error("目标会话已有正在运行的前台或后台请求。");
    }
    if (!input.session.provider_id || !input.session.model_id) {
      throw new Error("目标会话没有可用的模型配置。");
    }

    const request = buildConversationRunRequest({
      messages: [{
        role: "user",
        content: input.message,
        message_id: userMessageId,
      }],
      modelId: input.session.model_id,
      projectId: input.projectId,
      providerId: input.session.provider_id,
      reasoningMode: input.session.reasoning_mode,
      sessionId: input.session.session_id,
      settings: input.session.settings,
    });
    let resolveStarted!: (value: ConversationBackgroundRunStarted) => void;
    let rejectStarted!: (error: unknown) => void;
    let startedSettled = false;
    const started = new Promise<ConversationBackgroundRunStarted>((resolve, reject) => {
      resolveStarted = resolve;
      rejectStarted = reject;
    });
    const settleStarted = (
      value: ConversationBackgroundRunStarted | null,
      error?: unknown,
    ) => {
      if (startedSettled) return;
      startedSettled = true;
      if (value) resolveStarted(value);
      else rejectStarted(error);
    };

    const runCompletion = this.dependencies.followRun({
      expectedUserMessageId: userMessageId,
      initialStrategy: input.initialStrategy,
      request,
      onStarted: () => {
        settleStarted({ running: true, userMessageId });
        void Promise.resolve(input.onStarted?.()).catch(() => undefined);
      },
      onEvent: async (event) => {
        await processChatStreamEventSideEffects(event, input.clientToolExecutor());
      },
    }).then(async (settlement) => {
      const turn = await this.dependencies.loadTurn(
        input.projectId,
        input.session.session_id,
        userMessageId,
      );
      const result = buildRunResult(userMessageId, turn, settlement);
      settleStarted({ running: false, userMessageId });
      return result;
    }).catch((error) => {
      settleStarted(null, error);
      throw error;
    });

    const completion = runCompletion.then(
      async (result) => {
        await this.finishRun(key, userMessageId, input, result.outcome);
        return result;
      },
      async (error: unknown) => {
        await this.finishRun(key, userMessageId, input, null);
        throw error;
      },
    );
    const handle = { completion, started };
    this.runs.set(key, { handle, userMessageId });
    void completion.catch(() => undefined);
    return handle;
  }

  hasActiveRun(projectId: string, sessionId: string): boolean {
    return this.runs.has(`${projectId}:${sessionId}`);
  }

  private async finishRun(
    key: string,
    userMessageId: string,
    input: ConversationBackgroundRunInput,
    outcome: ConversationRunOutcome | null,
  ) {
    try {
      await input.onSettled?.(outcome);
    } catch {
      // UI refresh callbacks cannot change the persisted run outcome.
    } finally {
      const trackedRun = this.runs.get(key);
      if (trackedRun?.userMessageId === userMessageId) {
        this.runs.delete(key);
      }
    }
  }
}

let sharedConversationBackgroundRunRegistry: ConversationBackgroundRunRegistry | null = null;

export function getConversationBackgroundRunRegistry(): ConversationBackgroundRunRegistry {
  sharedConversationBackgroundRunRegistry ??= new ConversationBackgroundRunRegistry();
  return sharedConversationBackgroundRunRegistry;
}

function buildRunResult(
  expectedUserMessageId: string,
  turn: ConversationTurn,
  settlement: ConversationRunSettlement | null,
): ConversationBackgroundRunResult {
  if (turn.user.message_id !== expectedUserMessageId) {
    throw new Error("持久化轮次与本次发送的用户消息不一致。");
  }
  const persistedAssistantId = turn.reply?.message_id ?? null;
  const persistedOutcome = outcomeFromTurn(turn);
  if (settlement) {
    if (settlement.userMessageId !== expectedUserMessageId) {
      throw new Error("会话运行终态属于另一条用户消息。");
    }
    if (settlement.assistantMessageId !== persistedAssistantId) {
      throw new Error("会话运行终态与持久化回复身份不一致。");
    }
    if (persistedOutcome && settlement.outcome !== persistedOutcome) {
      throw new Error("会话运行终态与持久化回复状态不一致。");
    }
  }
  const outcome = settlement?.outcome ?? persistedOutcome;
  if (!outcome) {
    throw new Error("会话流已结束，但本次回复仍没有明确终态。");
  }
  return {
    assistantMessageId: persistedAssistantId,
    outcome,
    turn,
    userMessageId: expectedUserMessageId,
  };
}

function outcomeFromTurn(turn: ConversationTurn): ConversationRunOutcome | null {
  const reply = turn.reply;
  if (!reply) return null;
  if (reply.status === "cancelled") return "cancelled";
  if (reply.role === "error" || reply.status === "error") return "error";
  if (reply.status === "done") return "done";
  return null;
}
