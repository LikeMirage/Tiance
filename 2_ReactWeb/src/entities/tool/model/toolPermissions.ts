export const TOOL_PARAMETER_PERMISSION_TYPE_KEY = "permission_type";

export type ToolParameterPermissionType =
  | "none"
  | "filesystem_read"
  | "filesystem_write"
  | "filesystem_delete"
  | "program_execute"
  | "process_control"
  | "runtime_modify"
  | "network_access"
  | "credential_use"
  | "external_data_read"
  | "external_data_modify"
  | "tiance_data_read"
  | "tiance_data_write"
  | "tiance_data_delete"
  | "ui_control";

export type ToolParameterPermissionOption = {
  description: string;
  label: string;
  value: ToolParameterPermissionType | "";
};

export type ToolParameterPermissionGroup = {
  id: string;
  label: string;
  options: ToolParameterPermissionOption[];
};

export const TOOL_PARAMETER_PERMISSION_GROUPS: ToolParameterPermissionGroup[] = [
  {
    id: "general",
    label: "通用",
    options: [
      {
        value: "",
        label: "未知权限",
        description: "不声明权限类型；保存时删除该参数的权限数据。",
      },
      {
        value: "none",
        label: "无需检查",
        description: "普通配置或内容参数，不参与权限检查。",
      },
    ],
  },
  {
    id: "filesystem",
    label: "文件与系统",
    options: [
      { value: "filesystem_read", label: "文件系统读取", description: "读取或定位本机文件、目录。" },
      { value: "filesystem_write", label: "文件系统写入", description: "创建、覆盖或修改本机文件、目录。" },
      { value: "filesystem_delete", label: "文件系统删除", description: "删除本机文件、目录或其中内容。" },
      { value: "program_execute", label: "程序执行", description: "执行命令、脚本或本机程序。" },
      { value: "process_control", label: "进程控制", description: "查询、等待、终止或管理运行中的进程。" },
      { value: "runtime_modify", label: "运行环境修改", description: "安装依赖或改变工具运行环境。" },
    ],
  },
  {
    id: "network",
    label: "网络与外部",
    options: [
      { value: "network_access", label: "网络访问", description: "向互联网或局域网地址发起请求。" },
      { value: "credential_use", label: "凭据使用", description: "使用密钥、令牌或其他身份凭据。" },
      { value: "external_data_read", label: "外部数据读取", description: "读取外部服务、账户或仓库中的数据。" },
      { value: "external_data_modify", label: "外部数据变更", description: "创建、修改或删除外部服务中的数据。" },
    ],
  },
  {
    id: "tiance",
    label: "天策应用",
    options: [
      { value: "tiance_data_read", label: "天策数据读取", description: "读取天策项目、会话、记忆或设置。" },
      { value: "tiance_data_write", label: "天策数据写入", description: "创建或修改天策内部数据。" },
      { value: "tiance_data_delete", label: "天策数据删除", description: "删除天策项目、会话、记忆或设置。" },
      { value: "ui_control", label: "界面控制", description: "打开、切换或关闭天策界面内容。" },
    ],
  },
];

const TOOL_PARAMETER_PERMISSION_OPTIONS = TOOL_PARAMETER_PERMISSION_GROUPS.flatMap(
  (group) => group.options,
);

const STORED_PERMISSION_TYPES = new Set<ToolParameterPermissionType>(
  TOOL_PARAMETER_PERMISSION_OPTIONS
    .map((option) => option.value)
    .filter((value): value is ToolParameterPermissionType => value !== ""),
);

export function getToolParameterPermissionType(value: unknown): ToolParameterPermissionType | "" {
  return typeof value === "string" && STORED_PERMISSION_TYPES.has(value as ToolParameterPermissionType)
    ? value as ToolParameterPermissionType
    : "";
}

export function getToolParameterPermissionOption(value: unknown): ToolParameterPermissionOption {
  const normalized = getToolParameterPermissionType(value);
  return TOOL_PARAMETER_PERMISSION_OPTIONS.find((option) => option.value === normalized)
    ?? TOOL_PARAMETER_PERMISSION_GROUPS[0].options[0];
}

export function setToolParameterPermissionType(
  schema: Record<string, unknown>,
  value: ToolParameterPermissionType | "",
) {
  if (value) {
    schema[TOOL_PARAMETER_PERMISSION_TYPE_KEY] = value;
  } else {
    delete schema[TOOL_PARAMETER_PERMISSION_TYPE_KEY];
  }
}

export type ToolPermissionDecision = "deny" | "ask" | "allow";
export type ToolPermissionPolicyType = Exclude<ToolParameterPermissionType, "none"> | "unknown";

export type ToolPermissionScopeDefinition = {
  id: string;
  label: string;
};

export type ToolPermissionPolicyDefinition = {
  categoryId: string;
  categoryLabel: string;
  description: string;
  label: string;
  permissionType: ToolPermissionPolicyType;
  scopes: ToolPermissionScopeDefinition[];
};

const WORKSPACE_SCOPES: ToolPermissionScopeDefinition[] = [
  { id: "workspace_inside", label: "工作区内" },
  { id: "workspace_outside", label: "工作区外" },
  { id: "unresolved", label: "无法识别位置" },
];

const NETWORK_SCOPES: ToolPermissionScopeDefinition[] = [
  { id: "loopback", label: "本机地址" },
  { id: "private_network", label: "局域网" },
  { id: "public_network", label: "互联网" },
  { id: "unresolved", label: "无法识别目标" },
];

const TIANCE_DATA_SCOPES: ToolPermissionScopeDefinition[] = [
  { id: "current_project", label: "当前项目" },
  { id: "other_project", label: "其他项目" },
  { id: "global_data", label: "全局数据" },
  { id: "unresolved", label: "无法识别范围" },
];

const PROGRAM_SCOPES: ToolPermissionScopeDefinition[] = [
  { id: "workspace_program", label: "工作区程序" },
  { id: "system_program", label: "系统程序" },
  { id: "unresolved", label: "无法识别程序" },
];

const ALL_SCOPES: ToolPermissionScopeDefinition[] = [
  { id: "all", label: "所有调用" },
];

export const TOOL_PERMISSION_POLICY_DEFINITIONS: ToolPermissionPolicyDefinition[] = [
  {
    permissionType: "unknown",
    label: "未知权限",
    description: "参数没有声明权限类型时使用。",
    categoryId: "general",
    categoryLabel: "通用",
    scopes: ALL_SCOPES,
  },
  permissionDefinition("filesystem_read", "filesystem", "文件与系统", WORKSPACE_SCOPES),
  permissionDefinition("filesystem_write", "filesystem", "文件与系统", WORKSPACE_SCOPES),
  permissionDefinition("filesystem_delete", "filesystem", "文件与系统", WORKSPACE_SCOPES),
  permissionDefinition("program_execute", "filesystem", "文件与系统", PROGRAM_SCOPES),
  permissionDefinition("process_control", "filesystem", "文件与系统", ALL_SCOPES),
  permissionDefinition("runtime_modify", "filesystem", "文件与系统", ALL_SCOPES),
  permissionDefinition("network_access", "network", "网络与外部", NETWORK_SCOPES),
  permissionDefinition("credential_use", "network", "网络与外部", ALL_SCOPES),
  permissionDefinition("external_data_read", "network", "网络与外部", ALL_SCOPES),
  permissionDefinition("external_data_modify", "network", "网络与外部", ALL_SCOPES),
  permissionDefinition("tiance_data_read", "tiance", "天策应用", TIANCE_DATA_SCOPES),
  permissionDefinition("tiance_data_write", "tiance", "天策应用", TIANCE_DATA_SCOPES),
  permissionDefinition("tiance_data_delete", "tiance", "天策应用", TIANCE_DATA_SCOPES),
  permissionDefinition("ui_control", "tiance", "天策应用", ALL_SCOPES),
];

export type ToolPermissionPolicy = {
  fallback: ToolPermissionDecision;
  policies: Record<ToolPermissionPolicyType, Record<string, ToolPermissionDecision>>;
  version: 1;
};

const DEFAULT_TOOL_PERMISSION_POLICIES: ToolPermissionPolicy["policies"] = {
  unknown: { all: "ask" },
  filesystem_read: {
    workspace_inside: "allow",
    workspace_outside: "allow",
    unresolved: "allow",
  },
  filesystem_write: {
    workspace_inside: "allow",
    workspace_outside: "ask",
    unresolved: "ask",
  },
  filesystem_delete: {
    workspace_inside: "ask",
    workspace_outside: "deny",
    unresolved: "deny",
  },
  program_execute: {
    workspace_program: "allow",
    system_program: "ask",
    unresolved: "ask",
  },
  process_control: { all: "ask" },
  runtime_modify: { all: "ask" },
  network_access: {
    loopback: "allow",
    private_network: "ask",
    public_network: "allow",
    unresolved: "ask",
  },
  credential_use: { all: "ask" },
  external_data_read: { all: "allow" },
  external_data_modify: { all: "ask" },
  tiance_data_read: {
    current_project: "allow",
    other_project: "allow",
    global_data: "allow",
    unresolved: "allow",
  },
  tiance_data_write: {
    current_project: "allow",
    other_project: "ask",
    global_data: "ask",
    unresolved: "ask",
  },
  tiance_data_delete: {
    current_project: "ask",
    other_project: "ask",
    global_data: "ask",
    unresolved: "deny",
  },
  ui_control: { all: "allow" },
};

export function buildDefaultToolPermissionPolicy(
  fallback?: ToolPermissionDecision,
): ToolPermissionPolicy {
  const resolvedFallback = fallback ?? "ask";
  const useProductDefaults = fallback === undefined;
  return {
    version: 1,
    fallback: resolvedFallback,
    policies: Object.fromEntries(
      TOOL_PERMISSION_POLICY_DEFINITIONS.map((definition) => [
        definition.permissionType,
        Object.fromEntries(definition.scopes.map((scope) => [
          scope.id,
          useProductDefaults
            ? DEFAULT_TOOL_PERMISSION_POLICIES[definition.permissionType][scope.id]
            : resolvedFallback,
        ])),
      ]),
    ) as ToolPermissionPolicy["policies"],
  };
}

export function normalizeToolPermissionPolicy(value: unknown): ToolPermissionPolicy {
  if (!isJsonObject(value)) {
    throw new Error("permissions.json 必须是 JSON 对象。");
  }
  if (value.version !== 1) {
    throw new Error("permissions.json.version 必须为 1。");
  }
  if (!isToolPermissionDecision(value.fallback)) {
    throw new Error("permissions.json.fallback 必须是 deny、ask 或 allow。");
  }
  if (!isJsonObject(value.policies)) {
    throw new Error("permissions.json.policies 必须是 JSON 对象。");
  }

  const definitionsByType = new Map(
    TOOL_PERMISSION_POLICY_DEFINITIONS.map((definition) => [definition.permissionType, definition]),
  );
  for (const permissionType of Object.keys(value.policies)) {
    if (!definitionsByType.has(permissionType as ToolPermissionPolicyType)) {
      throw new Error(`permissions.json 包含未知权限点：${permissionType}。`);
    }
  }

  const normalized = buildDefaultToolPermissionPolicy(value.fallback);
  for (const definition of TOOL_PERMISSION_POLICY_DEFINITIONS) {
    const rawPolicy = value.policies[definition.permissionType];
    if (rawPolicy === undefined) continue;
    if (!isJsonObject(rawPolicy)) {
      throw new Error(`权限点 ${definition.permissionType} 的配置必须是 JSON 对象。`);
    }
    const scopeIds = new Set(definition.scopes.map((scope) => scope.id));
    for (const scope of Object.keys(rawPolicy)) {
      if (!scopeIds.has(scope)) {
        throw new Error(`权限点 ${definition.permissionType} 包含未知范围：${scope}。`);
      }
    }
    for (const scope of definition.scopes) {
      const decision = rawPolicy[scope.id];
      if (decision === undefined) continue;
      if (!isToolPermissionDecision(decision)) {
        throw new Error(
          `权限点 ${definition.permissionType} 的 ${scope.id} 必须是 deny、ask 或 allow。`,
        );
      }
      normalized.policies[definition.permissionType][scope.id] = decision;
    }
  }
  return normalized;
}

function permissionDefinition(
  permissionType: ToolPermissionPolicyType,
  categoryId: string,
  categoryLabel: string,
  scopes: ToolPermissionScopeDefinition[],
): ToolPermissionPolicyDefinition {
  const option = getToolParameterPermissionOption(permissionType);
  return {
    permissionType,
    categoryId,
    categoryLabel,
    scopes,
    label: option.label,
    description: option.description,
  };
}

function isToolPermissionDecision(value: unknown): value is ToolPermissionDecision {
  return value === "deny" || value === "ask" || value === "allow";
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
