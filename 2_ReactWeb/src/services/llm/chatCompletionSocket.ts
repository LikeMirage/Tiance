import type {
  ChatCompletionRequest,
  ChatStreamEvent,
} from "../../entities/llm-chat/model/chatCompletion";
import { env } from "../../shared/config/env";
import { createUuid } from "../../shared/model/createUuid";
import { HttpRequestError } from "../http/httpClient";
import { ChatSocketEventBuffer } from "./chatSocketEventBuffer";

type ChatSocketCommand =
  | {
    type: "start";
    request: ChatCompletionRequest;
  }
  | {
    type: "subscribe";
    project_id: string;
    session_id: string;
    checkpoint_message_id?: string;
  };

type ChatSocketMessage =
  | {
    type: "opened";
    channel_id: string;
  }
  | {
    type: "event";
    channel_id: string;
    event: ChatStreamEvent;
  }
  | {
    type: "complete";
    channel_id: string;
  }
  | {
    type: "error";
    channel_id: string;
    status?: number;
    code?: string | null;
    error?: string;
  };

type ChatSocketChannel = {
  eventBuffer: ChatSocketEventBuffer<ChatStreamEvent>;
  isProcessingEvents: boolean;
  onEvent: (event: ChatStreamEvent) => void | Promise<void>;
  onOpen?: () => void;
  reject: (error: unknown) => void;
  resolve: () => void;
  removeAbortListener: () => void;
  settled: boolean;
  terminalError: unknown;
  terminalRequested: boolean;
};

const CHANNEL_MAX_BUFFERED_EVENTS = 1024;
const CHANNEL_MAX_BUFFERED_CONTENT_UNITS = 8 * 1024 * 1024;

class ChatCompletionSocket {
  private socket: WebSocket | null = null;
  private connecting: Promise<WebSocket> | null = null;
  private readonly channels = new Map<string, ChatSocketChannel>();

  run(
    command: ChatSocketCommand,
    onEvent: (event: ChatStreamEvent) => void | Promise<void>,
    options: {
      onOpen?: () => void;
      signal?: AbortSignal;
    } = {},
  ): Promise<void> {
    if (options.signal?.aborted) {
      return Promise.reject(createAbortError());
    }

    const channelId = createUuid();
    return new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        this.sendUnsubscribe(channelId);
        this.settleChannel(channelId, createAbortError());
      };
      options.signal?.addEventListener("abort", onAbort, { once: true });

      this.channels.set(channelId, {
        eventBuffer: new ChatSocketEventBuffer(
          CHANNEL_MAX_BUFFERED_EVENTS,
          CHANNEL_MAX_BUFFERED_CONTENT_UNITS,
        ),
        isProcessingEvents: false,
        onEvent,
        onOpen: options.onOpen,
        reject,
        resolve,
        removeAbortListener: () => options.signal?.removeEventListener("abort", onAbort),
        settled: false,
        terminalError: undefined,
        terminalRequested: false,
      });

      void this.ensureSocket().then(
        (socket) => {
          if (!this.channels.has(channelId)) return;
          socket.send(JSON.stringify({
            ...command,
            channel_id: channelId,
          }));
        },
        (error) => this.settleChannel(channelId, error),
      );
    });
  }

  private ensureSocket(): Promise<WebSocket> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return Promise.resolve(this.socket);
    }
    if (this.connecting) {
      return this.connecting;
    }

    const socket = new WebSocket(buildChatSocketUrl());
    this.socket = socket;
    this.connecting = new Promise<WebSocket>((resolve, reject) => {
      socket.addEventListener("open", () => {
        if (this.socket !== socket) return;
        this.connecting = null;
        resolve(socket);
      }, { once: true });
      socket.addEventListener("error", () => {
        if (socket.readyState !== WebSocket.OPEN) {
          reject(new HttpRequestError(
            "无法连接会话流通道。",
            503,
            "chat_socket_connect_failed",
          ));
        }
      }, { once: true });
    });

    socket.addEventListener("message", (event) => this.handleMessage(event));
    socket.addEventListener("close", () => this.handleClose(socket));
    return this.connecting;
  }

  private handleMessage(messageEvent: MessageEvent<string>) {
    const message = parseSocketMessage(messageEvent.data);
    if (!message) return;
    const channel = this.channels.get(message.channel_id);
    if (!channel || channel.settled) return;

    if (message.type === "opened") {
      channel.onOpen?.();
      return;
    }

    if (message.type === "event") {
      this.enqueueChannelEvent(message.channel_id, channel, message.event);
      return;
    }

    if (message.type === "complete") {
      this.requestChannelSettlement(message.channel_id, channel);
      return;
    }

    const error = new HttpRequestError(
      message.error || "会话流通道返回错误。",
      message.status ?? 500,
      message.code ?? null,
    );
    this.requestChannelSettlement(message.channel_id, channel, error);
  }

  private enqueueChannelEvent(
    channelId: string,
    channel: ChatSocketChannel,
    event: ChatStreamEvent,
  ) {
    if (channel.terminalRequested) return;
    if (!channel.eventBuffer.tryPush(event)) {
      this.sendUnsubscribe(channelId);
      this.settleChannel(channelId, new HttpRequestError(
        "会话流处理速度不足，需要从已保存进度重新同步。",
        409,
        "conversation_stream_resync_required",
      ));
      return;
    }
    void this.drainChannelEvents(channelId, channel);
  }

  private async drainChannelEvents(channelId: string, channel: ChatSocketChannel) {
    if (channel.isProcessingEvents || channel.settled) return;
    channel.isProcessingEvents = true;
    try {
      while (this.channels.get(channelId) === channel && !channel.settled) {
        const bufferedEvent = channel.eventBuffer.take();
        if (!bufferedEvent) break;
        await channel.onEvent(bufferedEvent.value);
        channel.eventBuffer.release(bufferedEvent);
      }
    } catch (error) {
      this.sendUnsubscribe(channelId);
      this.settleChannel(channelId, error);
      return;
    } finally {
      channel.isProcessingEvents = false;
    }
    if (
      this.channels.get(channelId) === channel
      && channel.terminalRequested
      && channel.eventBuffer.pendingCount === 0
    ) {
      this.settleChannel(channelId, channel.terminalError);
    }
  }

  private requestChannelSettlement(
    channelId: string,
    channel: ChatSocketChannel,
    error?: unknown,
  ) {
    channel.terminalRequested = true;
    channel.terminalError = error;
    if (!channel.isProcessingEvents && channel.eventBuffer.pendingCount === 0) {
      this.settleChannel(channelId, error);
    }
  }

  private handleClose(closedSocket: WebSocket) {
    if (this.socket !== closedSocket) return;
    this.socket = null;
    this.connecting = null;
    const error = new HttpRequestError(
      "会话流连接已断开。",
      503,
      "chat_socket_closed",
    );
    for (const channelId of [...this.channels.keys()]) {
      this.settleChannel(channelId, error);
    }
  }

  private sendUnsubscribe(channelId: string) {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({
      type: "unsubscribe",
      channel_id: channelId,
    }));
  }

  private settleChannel(channelId: string, error?: unknown) {
    const channel = this.channels.get(channelId);
    if (!channel || channel.settled) return;
    channel.settled = true;
    channel.eventBuffer.clear();
    channel.removeAbortListener();
    this.channels.delete(channelId);
    if (error === undefined) {
      channel.resolve();
    } else {
      channel.reject(error);
    }
  }
}

let sharedChatCompletionSocket: ChatCompletionSocket | null = null;

export function streamChatCompletionOverSocket(
  request: ChatCompletionRequest,
  onEvent: (event: ChatStreamEvent) => void | Promise<void>,
  options: {
    onOpen?: () => void;
    signal?: AbortSignal;
  } = {},
) {
  sharedChatCompletionSocket ??= new ChatCompletionSocket();
  return sharedChatCompletionSocket.run(
    { type: "start", request },
    onEvent,
    options,
  );
}

export function resumeChatCompletionOverSocket(
  projectId: string,
  sessionId: string,
  onEvent: (event: ChatStreamEvent) => void | Promise<void>,
  options: {
    checkpointMessageId?: string | null;
    signal?: AbortSignal;
  } = {},
) {
  sharedChatCompletionSocket ??= new ChatCompletionSocket();
  return sharedChatCompletionSocket.run(
    {
      type: "subscribe",
      project_id: projectId,
      session_id: sessionId,
      ...(options.checkpointMessageId
        ? { checkpoint_message_id: options.checkpointMessageId }
        : {}),
    },
    onEvent,
    { signal: options.signal },
  );
}

function buildChatSocketUrl() {
  const url = new URL(env.apiBaseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/api/llm/chat/completions/socket`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

function parseSocketMessage(value: string): ChatSocketMessage | null {
  try {
    const parsed = JSON.parse(value) as ChatSocketMessage;
    if (!parsed || typeof parsed !== "object" || typeof parsed.channel_id !== "string") {
      return null;
    }
    if (!["opened", "event", "complete", "error"].includes(parsed.type)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function createAbortError() {
  return new DOMException("The operation was aborted.", "AbortError");
}
