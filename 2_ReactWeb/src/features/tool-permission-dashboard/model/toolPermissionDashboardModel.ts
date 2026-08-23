import {
  getToolParameterPermissionType,
  normalizeToolPermissionPolicy,
  type ToolPermissionPolicy,
  type ToolPermissionPolicyType,
} from "../../../entities/tool/model/toolPermissions";

export type ToolPermissionDashboardData = {
  inputSchema: Record<string, unknown>;
  permissionParameters: Map<ToolPermissionPolicyType | "none", string[]>;
  permissions: ToolPermissionPolicy;
  registrationName: string;
};

export type ParsedToolPermissionDashboard =
  | { data: ToolPermissionDashboardData; ok: true }
  | { error: string; ok: false };

export function parseToolPermissionDashboardContent(
  content: string,
): ParsedToolPermissionDashboard {
  try {
    const payload = JSON.parse(stripJsonBom(content)) as unknown;
    if (!isJsonObject(payload)) {
      throw new Error("权限看板内容必须是 JSON 对象。");
    }
    const inputSchema = isJsonObject(payload.input_schema) ? payload.input_schema : {};
    return {
      ok: true,
      data: {
        inputSchema,
        permissionParameters: collectPermissionParameters(inputSchema),
        permissions: normalizeToolPermissionPolicy(payload.permissions),
        registrationName: typeof payload.registration_name === "string"
          ? payload.registration_name.trim()
          : "",
      },
    };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "权限配置解析失败。",
    };
  }
}

export function formatToolPermissionDashboardContent(
  currentContent: string,
  permissions: ToolPermissionPolicy,
) {
  const current = JSON.parse(stripJsonBom(currentContent)) as Record<string, unknown>;
  return `${JSON.stringify({ ...current, permissions }, null, 2)}\n`;
}

function collectPermissionParameters(inputSchema: Record<string, unknown>) {
  const result = new Map<ToolPermissionPolicyType | "none", string[]>();
  const properties = isJsonObject(inputSchema.properties) ? inputSchema.properties : {};
  for (const [name, rawSchema] of Object.entries(properties)) {
    const schema = isJsonObject(rawSchema) ? rawSchema : {};
    const permissionType = getToolParameterPermissionType(schema.permission_type);
    const mapKey: ToolPermissionPolicyType | "none" = permissionType || "unknown";
    const names = result.get(mapKey) ?? [];
    names.push(name);
    result.set(mapKey, names);
  }
  return result;
}

function stripJsonBom(content: string) {
  return content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
