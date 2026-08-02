import { useCallback, useMemo, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";

import "./conversation-injection-preview.css";

type JsonObject = Record<string, unknown>;

type InjectionTool = {
  description: string;
  name: string;
  parameters: JsonObject;
};

type DynamicToolSummary = {
  description: string;
  displayName: string;
  examples: string[];
  name: string;
  parameterNames: string[];
};

type DynamicToolDirectory = {
  introLines: string[];
  tools: DynamicToolSummary[];
};

type InjectionRequestMessage = {
  content: string;
  index: number;
  role: string;
  source?: string;
  name?: string;
  toolCallId?: string;
  thinkingContent?: string;
  toolCalls: JsonObject[];
  contentParts: JsonObject[];
  memoryCompression?: MemoryCompressionPreview;
};

type MemoryCompressionPreview = {
  compressionId: string;
  itemCount: number;
  sourceMessageCount: number;
  sourceType: string;
};

type InjectionPreviewPayload = {
  description: string;
  generatedAt: string;
  request: JsonObject;
  requestMessages: InjectionRequestMessage[];
  tools: InjectionTool[];
};

type ConversationInjectionPreviewProps = {
  content: string;
};

export function ConversationInjectionPreview({ content }: ConversationInjectionPreviewProps) {
  const parsed = useMemo(() => parseInjectionPreview(content), [content]);
  const [expandedMessageKeys, setExpandedMessageKeys] = useState<Set<string>>(() => new Set());
  const [isToolSchemaCollapsed, setIsToolSchemaCollapsed] = useState(true);
  const toggleMessageExpanded = useCallback((message: InjectionRequestMessage) => {
    const key = messageCollapseKey(message);
    setExpandedMessageKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);
  const toggleToolSchemaExpanded = useCallback(() => {
    setIsToolSchemaCollapsed((isCollapsed) => !isCollapsed);
  }, []);

  if (!content.trim()) {
    return (
      <div className="conversation-injection-preview conversation-injection-preview--empty">
        <p>当前注入预览为空。输入或发送一次会话消息后会自动生成。</p>
      </div>
    );
  }

  if (!parsed.ok) {
    return (
      <div className="conversation-injection-preview conversation-injection-preview--empty">
        <p>{parsed.error}</p>
      </div>
    );
  }

  const payload = parsed.payload;
  const messageCount = payload.requestMessages.length || numberValue(payload.request.message_count);
  const systemMessageCount = numberValue(payload.request.system_message_count)
    || payload.requestMessages.filter((message) => message.role === "system").length;
  const memoryCompressionCount = payload.requestMessages.filter((message) => message.memoryCompression).length;
  const toolCallCount = payload.requestMessages.reduce(
    (total, message) => total + message.toolCalls.length,
    0,
  );

  return (
    <div className="conversation-injection-preview">
      <header className="conversation-injection-preview__header">
        <h2 className="conversation-injection-preview__title">注入预览管理</h2>
        <div className="conversation-injection-preview__metrics" aria-label="注入统计">
          <Metric label="消息" value={messageCount} />
          <Metric label="系统" value={systemMessageCount} />
          <Metric label="压缩记忆" value={memoryCompressionCount} />
          <Metric label="工具 Schema" value={payload.tools.length} />
          <Metric label="工具调用" value={toolCallCount} />
        </div>
      </header>

      <section className="conversation-injection-preview__request" aria-label="请求信息">
        <dl className="conversation-injection-preview__request-grid">
          <MetaItem label="服务商" value={stringValue(payload.request.provider_id)} />
          <MetaItem label="模型" value={stringValue(payload.request.model_id)} />
          <MetaItem label="项目 ID" value={stringValue(payload.request.project_id)} />
          <MetaItem label="会话 ID" value={stringValue(payload.request.session_id)} />
          <MetaItem label="预览来源" value={previewSourceLabel(stringValue(payload.request.preview_source))} />
          <MetaItem label="工具调用时返回思考内容" value={flagValue(payload.request.return_thinking_content)} />
          <MetaItem label="工具调用上限" value={stringValue(payload.request.max_tool_calls)} />
          <MetaItem label="等待工具结果续写" value={flagValue(payload.request.ends_with_tool_result)} />
          <MetaItem label="生成时间" value={formatTime(payload.generatedAt)} />
        </dl>
      </section>

      <section className="conversation-injection-preview__section" aria-label="正式工具参数">
        <SectionTitle count={payload.tools.length} title="工具 Schema" />
        <ToolSchemaRecord
          isCollapsed={isToolSchemaCollapsed}
          onToggle={toggleToolSchemaExpanded}
          tools={payload.tools}
        />
      </section>

      <section className="conversation-injection-preview__section" aria-label="完整请求消息">
        <SectionTitle count={payload.requestMessages.length} title="请求消息" />
        {payload.requestMessages.length > 0 ? (
          <div className="conversation-injection-preview__message-list">
            {payload.requestMessages.map((message) => {
              const key = messageCollapseKey(message);
              const isCollapsed = !expandedMessageKeys.has(key);
              return (
                <RequestMessageCard
                  key={key}
                  isCollapsed={isCollapsed}
                  message={message}
                  onToggle={() => toggleMessageExpanded(message)}
                />
              );
            })}
          </div>
        ) : (
          <EmptyLine text="当前快照没有记录完整请求消息。" />
        )}
      </section>
    </div>
  );
}

function RequestMessageCard({
  isCollapsed,
  message,
  onToggle,
}: {
  isCollapsed: boolean;
  message: InjectionRequestMessage;
  onToggle: () => void;
}) {
  const title = messageTitle(message);
  return (
    <article className={requestMessageRecordClassName(message, isCollapsed)}>
      <header
        className="conversation-injection-preview__record-head"
        title={isCollapsed ? "展开请求消息" : "折叠请求消息"}
        onClick={onToggle}
      >
        <div className="conversation-injection-preview__record-title-block">
          <h3 className="conversation-injection-preview__record-title">
            <span className="conversation-injection-preview__record-index">No. {message.index}</span>
            <span>{title}</span>
          </h3>
        </div>
        <div className="conversation-injection-preview__record-controls">
          {message.source ? <span className="conversation-injection-preview__record-source">{sourceLabel(message.source)}</span> : null}
          {message.name || message.toolCallId ? (
            <span className="conversation-injection-preview__record-source">
              {[message.name, message.toolCallId].filter(Boolean).join(" / ")}
            </span>
          ) : null}
          <dl className="conversation-injection-preview__record-facts" aria-label="请求消息属性">
            <div>
              <dt>角色</dt>
              <dd>{messageRoleLabel(message.role)}</dd>
            </div>
            {message.memoryCompression ? (
              <div>
                <dt>记忆</dt>
                <dd>{memoryCompressionShortLabel(message.memoryCompression)}</dd>
              </div>
            ) : null}
          </dl>
          <button
            className="conversation-injection-preview__record-toggle"
            type="button"
            aria-label={isCollapsed ? "展开请求消息" : "折叠请求消息"}
            aria-expanded={!isCollapsed}
            title={isCollapsed ? "展开" : "折叠"}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          >
            {isCollapsed ? (
              <CaretRight size={14} weight="bold" aria-hidden="true" />
            ) : (
              <CaretDown size={14} weight="bold" aria-hidden="true" />
            )}
          </button>
        </div>
      </header>

      {!isCollapsed ? (
        <>
          {message.memoryCompression ? (
            <div className="conversation-injection-preview__memory-source">
              {memoryCompressionLabel(message.memoryCompression)}
            </div>
          ) : null}
          {message.source === "dynamic_tool_directory" && message.content ? (
            <DynamicToolDirectoryView content={message.content} />
          ) : message.content ? (
            <pre>{message.content}</pre>
          ) : (
            <EmptyLine text="这条消息没有文本内容。" />
          )}
          {message.thinkingContent ? <LazyJsonDetails label="查看思考内容" value={message.thinkingContent} /> : null}
          {message.toolCalls.length > 0 ? <LazyJsonDetails label="查看工具调用" value={message.toolCalls} /> : null}
          {message.contentParts.length > 0 ? <LazyJsonDetails label="查看多模态内容" value={message.contentParts} /> : null}
        </>
      ) : null}
    </article>
  );
}

function ToolSchemaRecord({
  isCollapsed,
  onToggle,
  tools,
}: {
  isCollapsed: boolean;
  onToggle: () => void;
  tools: InjectionTool[];
}) {
  const totalParameterCount = tools.reduce((total, tool) => {
    return total + Object.keys(objectValue(tool.parameters.properties)).length;
  }, 0);
  const totalRequiredCount = tools.reduce((total, tool) => {
    return total + arrayValue(tool.parameters.required).length;
  }, 0);

  return (
    <article className={isCollapsed
      ? "conversation-injection-preview__record conversation-injection-preview__record--collapsed"
      : "conversation-injection-preview__record"}
    >
      <header
        className="conversation-injection-preview__record-head"
        title={isCollapsed ? "展开工具 Schema" : "折叠工具 Schema"}
        onClick={onToggle}
      >
        <div className="conversation-injection-preview__record-title-block">
          <h3 className="conversation-injection-preview__record-title">
            <span className="conversation-injection-preview__record-index">Schema</span>
            <span>顶层 tools 字段</span>
          </h3>
        </div>
        <div className="conversation-injection-preview__record-controls">
          <dl className="conversation-injection-preview__record-facts" aria-label="工具属性">
            <div>
              <dt>工具</dt>
              <dd>{tools.length}</dd>
            </div>
            <div>
              <dt>参数</dt>
              <dd>{totalParameterCount}</dd>
            </div>
            <div>
              <dt>必填</dt>
              <dd>{totalRequiredCount}</dd>
            </div>
          </dl>
          <button
            className="conversation-injection-preview__record-toggle"
            type="button"
            aria-label={isCollapsed ? "展开工具 Schema" : "折叠工具 Schema"}
            aria-expanded={!isCollapsed}
            title={isCollapsed ? "展开" : "折叠"}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          >
            {isCollapsed ? (
              <CaretRight size={14} weight="bold" aria-hidden="true" />
            ) : (
              <CaretDown size={14} weight="bold" aria-hidden="true" />
            )}
          </button>
        </div>
      </header>

      {!isCollapsed ? (
        <div className="conversation-injection-preview__tool-schema-body">
          {tools.length > 0 ? (
            <div className="conversation-injection-preview__schema-tool-list">
              {tools.map((tool, index) => (
                <ToolSchemaItem key={`${index}:${tool.name || ""}`} index={index} tool={tool} />
              ))}
            </div>
          ) : <EmptyLine text="本轮请求没有正式注入工具 Schema。" />}
        </div>
      ) : null}
    </article>
  );
}

function ToolSchemaItem({ index, tool }: { index: number; tool: InjectionTool }) {
  const properties = objectValue(tool.parameters.properties);
  const required = arrayValue(tool.parameters.required).map(String);
  const propertyNames = Object.keys(properties);

  return (
    <article className="conversation-injection-preview__schema-tool">
      <header>
        <h4>
          <span>No. {index + 1}</span>
          <strong>{tool.name || "未命名工具"}</strong>
        </h4>
        <span>{propertyNames.length} 个参数</span>
      </header>
      <p className="conversation-injection-preview__tool-description">{tool.description || "暂无说明。"}</p>
      {propertyNames.length > 0 ? (
        <div className="conversation-injection-preview__params">
          {propertyNames.map((name) => {
            const schema = objectValue(properties[name]);
            return (
              <div className="conversation-injection-preview__param" key={name}>
                <div>
                  <strong>{name}</strong>
                  {required.includes(name) ? <span>必填</span> : null}
                </div>
                <p>{stringValue(schema.description) || stringValue(schema.title) || "暂无说明。"}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <EmptyLine text="这个工具没有参数。" />
      )}

      <LazyJsonDetails label="查看原始参数 Schema" value={tool.parameters} />
    </article>
  );
}

function DynamicToolDirectoryView({ content }: { content: string }) {
  const directory = useMemo(() => parseDynamicToolDirectory(content), [content]);
  if (directory.tools.length === 0) return <pre>{content}</pre>;

  return (
    <div className="conversation-injection-preview__dynamic-directory">
      {directory.introLines.length > 0 ? (
        <div className="conversation-injection-preview__directory-intro">
          {directory.introLines.map((line, index) => <p key={`${index}:${line}`}>{line}</p>)}
        </div>
      ) : null}
      <div className="conversation-injection-preview__directory-tool-list">
        {directory.tools.map((tool, index) => (
          <article className="conversation-injection-preview__directory-tool" key={`${index}:${tool.name}`}>
            <header>
              <h4>
                <strong>{tool.name}</strong>
                {tool.displayName ? <span>{tool.displayName}</span> : null}
              </h4>
              <span>{tool.parameterNames.length} 个参数</span>
            </header>
            <p>{tool.description || "暂无说明。"}</p>
            {tool.parameterNames.length > 0 ? (
              <div className="conversation-injection-preview__directory-params">
                <span>参数</span>
                <p>{tool.parameterNames.join("、")}</p>
              </div>
            ) : null}
            {tool.examples.length > 0 ? (
              <div className="conversation-injection-preview__directory-examples">
                <span>应用示例</span>
                <ol>
                  {tool.examples.map((example) => <li key={example}>{example}</li>)}
                </ol>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

function LazyJsonDetails({ label, value }: { label: string; value: unknown }) {
  const [isOpen, setIsOpen] = useState(false);
  const jsonText = useMemo(() => isOpen ? JSON.stringify(value, null, 2) : "", [isOpen, value]);

  return (
    <details
      className="conversation-injection-preview__raw"
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary>{label}</summary>
      {isOpen ? <pre>{jsonText}</pre> : null}
    </details>
  );
}

function SectionTitle({ count, title }: { count: number; title: string }) {
  return (
    <header className="conversation-injection-preview__section-title">
      <h2>{title}</h2>
      <span>{count} 条</span>
    </header>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="conversation-injection-preview__metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="conversation-injection-preview__meta">
      <dt>{label}</dt>
      <dd>{value || "-"}</dd>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="conversation-injection-preview__empty-line">{text}</p>;
}

function parseInjectionPreview(content: string):
  | { ok: true; payload: InjectionPreviewPayload }
  | { ok: false; error: string } {
  try {
    const raw = JSON.parse(content) as unknown;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { ok: false, error: "注入预览必须是 JSON 对象。" };
    }
    const payload = raw as JsonObject;
    const requestSnapshot = objectValue(payload.request_snapshot);
    return {
      ok: true,
      payload: {
        description: stringValue(payload.description),
        generatedAt: stringValue(payload.generated_at),
        request: objectValue(payload.request),
        requestMessages: arrayValue(requestSnapshot.messages)
          .map(toRequestMessage)
          .filter((message): message is InjectionRequestMessage => message !== null),
        tools: arrayValue(requestSnapshot.tools)
          .map(toTool)
          .filter((tool): tool is InjectionTool => tool !== null),
      },
    };
  } catch {
    return { ok: false, error: "injection_preview.json 不是有效 JSON。" };
  }
}

function toRequestMessage(value: unknown): InjectionRequestMessage | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as JsonObject;
  return {
    content: stringValue(record.content),
    index: numberValue(record.index),
    role: stringValue(record.role) || "unknown",
    source: stringValue(record.source) || undefined,
    name: stringValue(record.name) || undefined,
    toolCallId: stringValue(record.tool_call_id) || undefined,
    thinkingContent: stringValue(record.thinking_content) || undefined,
    toolCalls: arrayValue(record.tool_calls).map(objectValue),
    contentParts: arrayValue(record.content_parts).map(objectValue),
    memoryCompression: toMemoryCompressionPreview(objectValue(record.preview_metadata).memory_compression),
  };
}

function toMemoryCompressionPreview(value: unknown): MemoryCompressionPreview | undefined {
  const record = objectValue(value);
  if (!Object.keys(record).length) return undefined;
  return {
    compressionId: stringValue(record.compression_id),
    itemCount: numberValue(record.item_count),
    sourceMessageCount: numberValue(record.source_message_count),
    sourceType: stringValue(record.source_type),
  };
}

function toTool(value: unknown): InjectionTool | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as JsonObject;
  return {
    description: stringValue(record.description),
    name: stringValue(record.name),
    parameters: objectValue(record.parameters),
  };
}

function objectValue(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function flagValue(value: unknown): string {
  return value === true ? "开启" : value === false ? "关闭" : "-";
}

function messageCollapseKey(message: InjectionRequestMessage): string {
  return `${message.index}:${message.role}:${message.toolCallId || ""}:${message.name || ""}`;
}

function requestMessageRecordClassName(message: InjectionRequestMessage, isCollapsed: boolean): string {
  const classNames = ["conversation-injection-preview__record"];
  if (isCollapsed) classNames.push("conversation-injection-preview__record--collapsed");
  if (message.memoryCompression) {
    classNames.push("conversation-injection-preview__record--memory");
  } else if (message.role === "assistant" && message.toolCalls.length > 0) {
    classNames.push("conversation-injection-preview__record--tool-call");
  } else if (message.role === "tool") {
    classNames.push("conversation-injection-preview__record--tool-result");
  }
  return classNames.join(" ");
}

function messageTitle(message: InjectionRequestMessage): string {
  if (message.memoryCompression) {
    return "历史压缩摘要";
  }
  const content = firstLine(message.content);
  if (content) return content;
  if (message.toolCalls.length > 0) return "工具调用";
  if (message.contentParts.length > 0) return "多模态消息";
  return `${messageRoleLabel(message.role)} 消息`;
}

function firstLine(value: string): string {
  return value.trim().split(/\r?\n/, 1)[0]?.trim() || "";
}

function sourceLabel(source: string): string {
  if (source === "dynamic_tool_directory") return "动态工具目录";
  if (source === "workspace_info") return "工作区信息";
  return "系统提示词";
}

function memoryCompressionShortLabel(value: MemoryCompressionPreview): string {
  return value.sourceMessageCount > 0 ? `${value.sourceMessageCount} 条消息` : "累计摘要";
}

function memoryCompressionLabel(value: MemoryCompressionPreview): string {
  const source = value.sourceMessageCount > 0
    ? `覆盖 ${value.sourceMessageCount} 条消息`
    : "累计摘要";
  const itemCount = value.itemCount > 0 ? `${value.itemCount} 条` : "";
  return ["历史压缩摘要", source, itemCount]
    .filter(Boolean)
    .join(" · ");
}

function previewSourceLabel(source: string): string {
  if (source === "draft_request") return "输入框预览";
  if (source === "real_request") return "真实请求";
  return source || "-";
}

function messageRoleLabel(role: string): string {
  if (role === "system") return "system";
  if (role === "user") return "user";
  if (role === "assistant") return "assistant";
  if (role === "tool") return "tool";
  return role || "unknown";
}

function formatTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function parseDynamicToolDirectory(content: string): DynamicToolDirectory {
  const lines = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const introLines: string[] = [];
  const tools: DynamicToolSummary[] = [];
  let currentTool: DynamicToolSummary | null = null;
  let inExamples = false;

  const pushCurrentTool = () => {
    if (currentTool) tools.push(currentTool);
  };

  for (const line of lines) {
    if (line === "【动态加载工具目录】") continue;

    const toolName = readPrefixedLine(line, "工具：");
    if (toolName) {
      pushCurrentTool();
      currentTool = {
        description: "",
        displayName: "",
        examples: [],
        name: toolName,
        parameterNames: [],
      };
      inExamples = false;
      continue;
    }

    if (!currentTool) {
      introLines.push(line);
      continue;
    }

    const displayName = readPrefixedLine(line, "显示名称：");
    if (displayName) {
      currentTool.displayName = displayName;
      inExamples = false;
      continue;
    }

    const description = readPrefixedLine(line, "说明：");
    if (description) {
      currentTool.description = description;
      inExamples = false;
      continue;
    }

    const parameterNames = readPrefixedLine(line, "参数名：");
    if (parameterNames) {
      currentTool.parameterNames = parameterNames
        .split(/[,，、]/)
        .map((name) => name.trim())
        .filter(Boolean);
      inExamples = false;
      continue;
    }

    if (line === "应用示例：") {
      inExamples = true;
      continue;
    }

    if (inExamples) {
      currentTool.examples.push(line.replace(/^\d+[.．、]\s*/, ""));
    } else if (currentTool.description) {
      currentTool.description = `${currentTool.description} ${line}`;
    } else {
      currentTool.description = line;
    }
  }

  pushCurrentTool();
  return { introLines, tools };
}

function readPrefixedLine(line: string, prefix: string): string {
  return line.startsWith(prefix) ? line.slice(prefix.length).trim() : "";
}
