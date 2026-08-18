export type ToolManifest = {
  context?: {
    ai_instructions?: unknown;
    when_not_to_use?: unknown;
    when_to_use?: unknown;
  };
  description?: unknown;
  registration_name?: unknown;
  examples?: unknown;
  execution?: {
    parallel?: unknown;
  };
  input_schema?: JsonSchemaObject;
  loading?: {
    dynamic?: unknown;
  };
  name?: unknown;
  output_schema?: JsonSchemaObject;
  runtime?: {
    entry?: unknown;
    timeout_seconds?: unknown;
    type?: unknown;
  };
  state?: {
    enabled?: unknown;
  };
  keywords?: unknown;
};

export type JsonSchemaObject = {
  description?: unknown;
  properties?: Record<string, JsonSchemaProperty>;
  required?: unknown;
  type?: unknown;
};

export type JsonSchemaProperty = {
  additionalProperties?: unknown;
  default?: unknown;
  description?: unknown;
  enum?: unknown;
  format?: unknown;
  items?: unknown;
  maximum?: unknown;
  maxItems?: unknown;
  maxLength?: unknown;
  minimum?: unknown;
  minItems?: unknown;
  minLength?: unknown;
  multipleOf?: unknown;
  options?: unknown;
  title?: unknown;
  type?: unknown;
  uniqueItems?: unknown;
};

export type ToolManifestExample = {
  content?: unknown;
  enabled?: unknown;
  inject_content?: unknown;
  title?: unknown;
};

export type ParsedToolManifest =
  | { manifest: ToolManifest; ok: true }
  | { error: string; ok: false };

export function parseToolManifest(content: string): ParsedToolManifest {
  try {
    const payload = JSON.parse(stripJsonBom(content)) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return { ok: false, error: "tool.json 必须是一个 JSON 对象。" };
    }
    return { ok: true, manifest: payload as ToolManifest };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "JSON 解析失败。",
    };
  }
}

function stripJsonBom(content: string) {
  return content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
}

export function asString(value: unknown, defaultValue = "") {
  return typeof value === "string" && value.trim() ? value : defaultValue;
}

export function asStringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

export function asRequiredSet(value: unknown) {
  return new Set(asStringArray(value));
}
