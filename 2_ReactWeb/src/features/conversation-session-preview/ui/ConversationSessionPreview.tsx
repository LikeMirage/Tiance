import { useMemo, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";

import "../../conversation-messages-preview/ui/conversation-messages-preview.css";

type JsonObject = Record<string, unknown>;

type SessionSection = {
  entries: Array<{ label: string; value: string }>;
  id: string;
  title: string;
};

type ConversationSessionPreviewProps = {
  content: string;
};

export function ConversationSessionPreview({ content }: ConversationSessionPreviewProps) {
  const parsed = useMemo(() => parseJsonObject(content), [content]);
  const [expandedSectionIds, setExpandedSectionIds] = useState<Set<string>>(() => new Set());

  if (!content.trim()) {
    return (
      <div className="conversation-messages-preview conversation-messages-preview--empty">
        <p>当前会话配置为空。</p>
      </div>
    );
  }

  if (!parsed.ok) {
    return (
      <div className="conversation-messages-preview conversation-messages-preview--empty">
        <p>{parsed.error}</p>
      </div>
    );
  }

  const session = parsed.value;
  const settings = objectValue(session.settings);
  const sections = buildSessionSections(session, settings);
  const enabledToolNames = arrayValue(settings.enabled_tool_names).map(String);

  const toggleSection = (section: SessionSection) => {
    setExpandedSectionIds((current) => {
      const next = new Set(current);
      if (next.has(section.id)) {
        next.delete(section.id);
      } else {
        next.add(section.id);
      }
      return next;
    });
  };

  return (
    <div className="conversation-messages-preview">
      <header className="conversation-messages-preview__header">
        <h2 className="conversation-messages-preview__title">会话配置看板</h2>
        <div className="conversation-messages-preview__metrics" aria-label="会话配置统计">
          <Metric label="消息" value={stringValue(session.message_count) || "0"} />
          <Metric label="序号" value={stringValue(session.sequence_number) || "-"} />
          <Metric label="记忆压缩" value={flagValue(settings.memory_compression_enabled)} />
          <Metric label="工具" value={settings.enabled_tool_names === null ? "全部" : enabledToolNames.length} />
          <Metric label="压缩阈值" value={stringValue(settings.memory_context_token_trigger_threshold) || "-"} />
        </div>
      </header>

      <section className="conversation-messages-preview__request" aria-label="会话基础信息">
        <dl className="conversation-messages-preview__request-grid">
          <MetaItem label="标题" value={stringValue(session.title)} />
          <MetaItem label="会话 ID" value={stringValue(session.session_id)} />
          <MetaItem label="模型" value={[stringValue(session.provider_id), stringValue(session.model_id)].filter(Boolean).join(" / ")} />
          <MetaItem label="思考模式" value={stringValue(session.reasoning_mode)} />
          <MetaItem label="创建时间" value={formatTime(stringValue(session.created_at))} />
          <MetaItem label="更新时间" value={formatTime(stringValue(session.updated_at))} />
        </dl>
      </section>

      <section className="conversation-messages-preview__section" aria-label="配置分组">
        <SectionTitle count={sections.length} title="配置分组" />
        <div className="conversation-messages-preview__message-list">
          {sections.map((section, index) => {
            const isCollapsed = !expandedSectionIds.has(section.id);
            return (
              <SessionSectionCard
                key={section.id}
                index={index + 1}
                isCollapsed={isCollapsed}
                section={section}
                onToggle={() => toggleSection(section)}
              />
            );
          })}
        </div>
      </section>
    </div>
  );
}

function SessionSectionCard({
  index,
  isCollapsed,
  onToggle,
  section,
}: {
  index: number;
  isCollapsed: boolean;
  onToggle: () => void;
  section: SessionSection;
}) {
  return (
    <article className={isCollapsed ? "conversation-messages-preview__record conversation-messages-preview__record--collapsed" : "conversation-messages-preview__record"}>
      <header
        className="conversation-messages-preview__record-head"
        title={isCollapsed ? "展开配置分组" : "折叠配置分组"}
        onClick={onToggle}
      >
        <div className="conversation-messages-preview__record-title-block">
          <h3 className="conversation-messages-preview__record-title">
            <span className="conversation-messages-preview__record-index">No. {index}</span>
            <span>{section.title}</span>
          </h3>
        </div>
        <div className="conversation-messages-preview__record-controls">
          <dl className="conversation-messages-preview__record-facts" aria-label="配置分组属性">
            <div>
              <dt>字段</dt>
              <dd>{section.entries.length}</dd>
            </div>
          </dl>
          <button
            className="conversation-messages-preview__record-toggle"
            type="button"
            aria-label={isCollapsed ? "展开配置分组" : "折叠配置分组"}
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
        <dl className="conversation-messages-preview__meta-grid">
          {section.entries.map((entry) => (
            <MetaItem key={`${section.id}:${entry.label}`} label={entry.label} value={entry.value} />
          ))}
        </dl>
      ) : null}
    </article>
  );
}

function buildSessionSections(session: JsonObject, settings: JsonObject): SessionSection[] {
  const enabledToolNames = arrayValue(settings.enabled_tool_names).map(String);
  return [
    {
      id: "basic",
      title: "基础信息",
      entries: [
        { label: "会话 ID", value: stringValue(session.session_id) },
        { label: "标题", value: stringValue(session.title) },
        { label: "手动标题", value: flagValue(session.manual_title) },
        { label: "消息数量", value: stringValue(session.message_count) },
        { label: "创建时间", value: formatTime(stringValue(session.created_at)) },
        { label: "更新时间", value: formatTime(stringValue(session.updated_at)) },
      ],
    },
    {
      id: "model",
      title: "模型与生成",
      entries: [
        { label: "供应商", value: stringValue(session.provider_id) },
        { label: "模型", value: stringValue(session.model_id) },
        { label: "思考模式", value: stringValue(session.reasoning_mode) },
        { label: "最大输出", value: stringValue(settings.max_output_tokens) },
        { label: "温度", value: nullableValue(settings.temperature) },
        { label: "Top P", value: nullableValue(settings.top_p) },
        { label: "流式输出", value: flagValue(settings.streaming_enabled) },
      ],
    },
    {
      id: "memory",
      title: "记忆设置",
      entries: [
        { label: "全局记忆", value: flagValue(settings.global_memory_enabled) },
        { label: "项目记忆", value: flagValue(settings.project_memory_enabled) },
        { label: "记忆压缩", value: flagValue(settings.memory_compression_enabled) },
        {
          label: "原文保护区 Token",
          value: stringValue(settings.memory_raw_context_token_reserve),
        },
        {
          label: "上下文 Token 触发阈值",
          value: stringValue(settings.memory_context_token_trigger_threshold),
        },
      ],
    },
    {
      id: "tools",
      title: "工具与注入",
      entries: [
        { label: "注入用户消息时间戳", value: flagValue(settings.inject_message_timestamps) },
        { label: "工具调用容错", value: flagValue(settings.malformed_tool_call_recovery_enabled) },
        { label: "工具调用上限", value: stringValue(settings.max_tool_calls) },
        { label: "启用工具", value: settings.enabled_tool_names === null ? "全部工具" : enabledToolNames.join("、") },
        { label: "取消消息返回", value: flagValue(settings.return_cancelled_messages) },
        { label: "取消前用户消息", value: flagValue(settings.return_user_before_cancelled) },
      ],
    },
    {
      id: "prompt",
      title: "系统提示词",
      entries: [
        { label: "内容", value: stringValue(settings.system_prompt) || "空" },
      ],
    },
  ];
}

function SectionTitle({ count, title }: { count: number; title: string }) {
  return (
    <header className="conversation-messages-preview__section-title">
      <h2>{title}</h2>
      <span>{count} 组</span>
    </header>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="conversation-messages-preview__metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="conversation-messages-preview__meta">
      <dt>{label}</dt>
      <dd title={value || "-"}>{value || "-"}</dd>
    </div>
  );
}

function parseJsonObject(content: string): { ok: true; value: JsonObject } | { ok: false; error: string } {
  try {
    const value = JSON.parse(content) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { ok: false, error: "session.json 必须是 JSON 对象。" };
    }
    return { ok: true, value: value as JsonObject };
  } catch {
    return { ok: false, error: "session.json 不是有效 JSON。" };
  }
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

function nullableValue(value: unknown): string {
  if (value === null) return "null";
  return stringValue(value);
}

function flagValue(value: unknown): string {
  return value === true ? "开启" : value === false ? "关闭" : "-";
}

function formatTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}
