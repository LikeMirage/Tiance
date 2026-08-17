import type {
  ChatClientCapability,
  ChatClientToolRequestEvent,
} from "../../../entities/llm-chat/model/chatCompletion";

export type ClientToolExecutionResult = {
  ok: boolean;
  content?: unknown;
  error?: string | null;
};

export type ClientToolExecutor = (
  request: ChatClientToolRequestEvent,
  context: Readonly<{ signal: AbortSignal }>,
) => Promise<ClientToolExecutionResult>;

export type ClientToolRegistration = Readonly<{
  capability: ChatClientCapability;
  execute: ClientToolExecutor;
}>;

export type ClientToolRegistry = Readonly<{
  execute: ClientToolExecutor;
  capabilities: readonly ChatClientCapability[];
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
  const handlers = new Map<string, ClientToolRegistration>();
  for (const registration of registrations) {
    const capability = validateCapability(registration.capability);
    if (handlers.has(capability.name)) {
      throw new Error(`前端能力重复注册：${capability.name}`);
    }
    handlers.set(capability.name, { ...registration, capability });
  }

  const capabilities = Object.freeze(
    [...handlers.values()].map((registration) => registration.capability),
  );
  const execute: ClientToolExecutor = async (request, context) => {
    const required = request.client_capability;
    if (!required) return unsupportedClientToolResult(request.name, "请求缺少前端能力合同");
    const registration = handlers.get(required.name);
    if (!registration || registration.capability.version < required.min_version) {
      return unsupportedClientToolResult(
        request.name,
        `缺少前端能力 ${required.name} v${required.min_version}`,
      );
    }
    return registration.execute(request, context);
  };

  return Object.freeze({
    execute,
    capabilities,
  });
}

export function unsupportedClientToolResult(
  name: string,
  reason = "前端未注册所需能力",
): ClientToolExecutionResult {
  return {
    ok: false,
    content: {
      tool: name,
    },
    error: `${reason}：${name}`,
  };
}

function validateCapability(value: ChatClientCapability): ChatClientCapability {
  const name = value.name.trim();
  if (!name) throw new Error("前端能力名称不能为空。");
  if (name !== value.name) throw new Error("前端能力名称不能包含首尾空白。");
  if (!Number.isSafeInteger(value.version) || value.version < 1) {
    throw new Error(`前端能力版本无效：${name}`);
  }
  return Object.freeze({ name, version: value.version });
}
