import type { RoleConfigurationEditor } from "../model/useRoleConfigurationEditor";
import { RoleField, RoleNumberInput, RoleSection, RoleToggle } from "./RoleConfigurationFields";

export function RolePromptPanel({ editor }: { editor: RoleConfigurationEditor }) {
  const prompt = editor.configuration?.prompt;
  if (!prompt) return null;
  return (
    <RoleSection
      title="系统提示词"
      description="定义角色的职责、处理规则和输出方式。"
    >
      <RoleField label="系统提示词" wide>
        <textarea
          className="role-dashboard__textarea role-dashboard__textarea--prompt"
          spellCheck={false}
          value={prompt.system_prompt}
          onChange={(event) => editor.updateSection("prompt", {
            system_prompt: event.target.value,
          })}
        />
      </RoleField>
    </RoleSection>
  );
}

export function RoleResponseContextPanel({
  editor,
}: {
  editor: RoleConfigurationEditor;
}) {
  const configuration = editor.configuration;
  if (!configuration) return null;
  const { context, response } = configuration;
  return (
    <div className="role-dashboard__panel-grid">
      <RoleSection title="回复行为">
        <div className="role-dashboard__toggle-grid">
          <RoleToggle
            checked={response.return_thinking_content}
            label="工具调用时返回思考内容"
            onChange={(value) => editor.updateSection("response", {
              ...response,
              return_thinking_content: value,
            })}
          />
          <RoleToggle
            checked={response.return_cancelled_messages}
            label="返回被取消消息"
            onChange={(value) => editor.updateSection("response", {
              ...response,
              return_cancelled_messages: value,
            })}
          />
          <RoleToggle
            checked={response.return_user_before_cancelled}
            label="返回截断前用户消息"
            onChange={(value) => editor.updateSection("response", {
              ...response,
              return_user_before_cancelled: value,
            })}
          />
          <RoleToggle
            checked={response.streaming_enabled}
            label="流式输出"
            onChange={(value) => editor.updateSection("response", {
              ...response,
              streaming_enabled: value,
            })}
          />
          <RoleToggle
            checked={response.auto_collapse_assistant_process}
            label="自动折叠处理过程"
            onChange={(value) => editor.updateSection("response", {
              ...response,
              auto_collapse_assistant_process: value,
            })}
          />
        </div>
      </RoleSection>
      <RoleSection title="上下文注入">
        <div className="role-dashboard__toggle-grid">
          <RoleToggle
            checked={context.inject_message_timestamps}
            label="注入用户消息时间戳"
            onChange={(value) => editor.updateSection("context", {
              ...context,
              inject_message_timestamps: value,
            })}
          />
        </div>
      </RoleSection>
    </div>
  );
}

export function RoleMemoryPanel({ editor }: { editor: RoleConfigurationEditor }) {
  const memory = editor.configuration?.memory;
  if (!memory) return null;
  return (
    <div className="role-dashboard__panel-grid">
      <RoleSection title="记忆开关">
        <div className="role-dashboard__toggle-grid">
          <RoleToggle
            checked={memory.global_memory_enabled}
            label="接收全局记忆"
            onChange={(value) => editor.updateSection("memory", {
              ...memory,
              global_memory_enabled: value,
            })}
          />
          <RoleToggle
            checked={memory.project_memory_enabled}
            label="接收角色工作区记忆"
            onChange={(value) => editor.updateSection("memory", {
              ...memory,
              project_memory_enabled: value,
            })}
          />
          <RoleToggle
            checked={memory.global_memory_extraction_enabled}
            label="提取全局记忆"
            onChange={(value) => editor.updateSection("memory", {
              ...memory,
              global_memory_extraction_enabled: value,
            })}
          />
          <RoleToggle
            checked={memory.project_memory_extraction_enabled}
            label="提取角色工作区记忆"
            onChange={(value) => editor.updateSection("memory", {
              ...memory,
              project_memory_extraction_enabled: value,
            })}
          />
          <RoleToggle
            checked={memory.memory_compression_enabled}
            label="记忆压缩"
            onChange={(value) => editor.updateSection("memory", {
              ...memory,
              memory_compression_enabled: value,
            })}
          />
        </div>
      </RoleSection>
      <RoleSection title="压缩参数">
        <div className="role-dashboard__form-grid">
          <RoleField label="上下文触发阈值">
            <RoleNumberInput
              min={1}
              value={memory.memory_context_token_trigger_threshold}
              onCommit={(value) => editor.updateSection("memory", {
                ...memory,
                memory_context_token_trigger_threshold: value ?? 1,
              })}
            />
          </RoleField>
          <RoleField label="原始上下文保留量">
            <RoleNumberInput
              min={0}
              value={memory.memory_raw_context_token_reserve}
              onCommit={(value) => editor.updateSection("memory", {
                ...memory,
                memory_raw_context_token_reserve: value ?? 0,
              })}
            />
          </RoleField>
        </div>
      </RoleSection>
    </div>
  );
}
