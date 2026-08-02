import type { ChatClientToolRequestEvent } from "../../../entities/llm-chat/model/chatCompletion";

export type ClientToolExecutionResult = {
  ok: boolean;
  content?: unknown;
  error?: string | null;
};

export type ClientToolExecutor = (
  request: ChatClientToolRequestEvent,
) => Promise<ClientToolExecutionResult>;

export type ClientToolRegistration = Readonly<{
  name: string;
  execute: ClientToolExecutor;
}>;

export type ClientToolRegistry = Readonly<{
  execute: ClientToolExecutor;
  has: (name: string) => boolean;
  names: readonly string[];
}>;

/**
 * Builds one executor from independently owned client-tool handlers.
 *
 * Tool names are intentionally registered up front: duplicate ownership fails
 * during construction instead of depending on handler order at runtime.
 */
export function createClientToolRegistry(
  registrations: readonly ClientToolRegistration[],
): ClientToolRegistry {
  const handlers = new Map<string, ClientToolExecutor>();
  for (const registration of registrations) {
    const name = validateRegisteredToolName(registration.name);
    if (handlers.has(name)) {
      throw new Error(`客户端工具重复注册：${name}`);
    }
    handlers.set(name, registration.execute);
  }

  const names = Object.freeze([...handlers.keys()]);
  const execute: ClientToolExecutor = async (request) => {
    const handler = handlers.get(request.name);
    return handler
      ? handler(request)
      : unsupportedClientToolResult(request.name);
  };

  return Object.freeze({
    execute,
    has: (name: string) => handlers.has(name),
    names,
  });
}

export function unsupportedClientToolResult(name: string): ClientToolExecutionResult {
  return {
    ok: false,
    content: {
      tool: name,
    },
    error: `前端未注册客户端工具：${name}`,
  };
}

function validateRegisteredToolName(value: string): string {
  const name = value.trim();
  if (!name) {
    throw new Error("客户端工具注册名称不能为空。");
  }
  if (name !== value) {
    throw new Error(`客户端工具注册名称不能包含首尾空白：${JSON.stringify(value)}`);
  }
  return name;
}
