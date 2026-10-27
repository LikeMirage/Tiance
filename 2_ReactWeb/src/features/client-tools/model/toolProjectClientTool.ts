import type { ToolFolder } from "../../../entities/tool/model/toolset";
import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import { publishToolCatalogChange } from "../../../entities/tool/model/toolCatalogEvents";
import { createToolset } from "../../../services/tools/createToolset";
import { createToolFolder } from "../../../services/tools/createToolFolder";
import { getToolsets } from "../../../services/tools/getToolsets";
import { createToolFolderFileWorkspaceApi } from "../../../services/tools/toolFolderFileWorkspaceApi";
import type { ClientToolRegistration } from "./clientToolBridge";
import {
  clientToolFailure, clientToolSuccess, parseClientToolArguments, readRequiredString,
} from "./conversationClientToolValues";
import { instantiateToolProjectScaffold, loadToolProjectScaffold } from "./toolProjectScaffold";

export const TOOL_PROJECT_CAPABILITY = Object.freeze({ name: "tool.projects", version: 1 });

export function createToolProjectClientToolRegistration(): ClientToolRegistration {
  return { capability: TOOL_PROJECT_CAPABILITY, execute: executeToolProjectAction };
}

async function executeToolProjectAction(
  request: Parameters<ClientToolRegistration["execute"]>[0],
  { signal }: Parameters<ClientToolRegistration["execute"]>[1],
) {
  let action = "";
  let created: ToolFolder | null = null;
  let creationStarted = false;
  let attemptedFile: string | null = null;
  const writtenFiles: string[] = [];
  try {
    signal.throwIfAborted();
    const args = parseClientToolArguments(request.arguments);
    action = readRequiredString(args, "action");
    if (action === "list_categories") {
      exactKeys(args, ["action"]);
      const { items } = await getToolsets();
      signal.throwIfAborted();
      return clientToolSuccess({ action, categories: items.map(({ category_id, name, readonly }) => (
        { category_id, name, readonly }
      )) });
    }
    if (action === "create_category") {
      exactKeys(args, ["action", "name"]);
      const name = displayName(args);
      signal.throwIfAborted();
      creationStarted = true;
      // Once POST starts, await its result even after cancellation so the created identity is not lost.
      const category = await createToolset({ name });
      publishToolCatalogChange({ kind: "toolsets" });
      dispatchProjectCatalogChanged();
      return clientToolSuccess({ action, category });
    }
    if (action !== "create_tool") throw new Error(`不支持的动作：${action}`);
    exactKeys(args, ["action", "category_id", "name", "call_name"]);
    const name = displayName(args);
    const categoryId = readRequiredString(args, "category_id");
    const explicitCallName = args.call_name === undefined ? null : readRequiredString(args, "call_name");
    if (explicitCallName !== null && !/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(explicitCallName)) {
      throw new Error("call_name 须为 1–64 位英文、数字或下划线，不能以数字开头。");
    }
    const toolProjectId = readRequiredString(request, "tool_project_id");
    const { items } = await getToolsets();
    const category = items.find((item) => item.category_id === categoryId);
    if (!category || category.readonly) throw new Error("工具分类不存在或不可写，请先查看分类。");
    const scaffold = await loadToolProjectScaffold(toolProjectId, signal);
    signal.throwIfAborted();
    creationStarted = true;
    created = await createToolFolder(categoryId, { name });
    notifyCreated(created);
    const callName = explicitCallName ?? `tool_${created.project_id.replaceAll("-", "")}`;
    const files = instantiateToolProjectScaffold(scaffold, name, callName);
    const workspace = createToolFolderFileWorkspaceApi(categoryId, created.project_id);
    for (const file of files) {
      signal.throwIfAborted();
      attemptedFile = file.path;
      await workspace.saveTextFile(file.path, file.content, { signal });
      writtenFiles.push(file.path);
    }
    publishToolCatalogChange({ kind: "metadata", folderId: created.project_id, toolsetId: categoryId });
    const root = created.root_path.replaceAll("\\", "/").replace(/\/$/, "");
    return clientToolSuccess({
      action, project: created, call_name: callName, enabled: false,
      template_version: scaffold.version, files: writtenFiles,
      documentation_path: `${root}/${scaffold.documentation}`,
      manifest_path: `${root}/.tool/tool.json`,
      guidance: [
        `开始制作工具前，请先读取 ${root}/${scaffold.documentation}，再按索引阅读参数、权限、能力桥和测试资料。`,
        "这是尚未实现业务功能的完整模板，工具默认关闭；示例程序只返回未实现提示。",
        `完成实现并验证后，按用户意愿决定是否开启；如需开启，把 ${root}/.tool/tool.json 的 state.enabled 改为 true。`,
        "全局开启后，目标会话也需允许使用该工具。不要仅因模板已创建就自动启用。",
      ],
    });
  } catch (error) {
    return clientToolFailure(error, {
      action, created: created !== null, project: created,
      status: created ? "incomplete" : creationStarted ? "creation_outcome_unknown" : "not_created",
      written_files: writtenFiles, attempted_file: attemptedFile,
      guidance: created
        ? "项目已经创建，初始化未全部完成。请检查返回路径并在此项目内继续修复；不要重复创建。新模板不会被自动启用。"
        : creationStarted
          ? "创建请求已发出但未收到可确认结果，请先检查目标分类，避免重复创建。"
          : "未创建项目或分类，请修正错误后重试。",
    });
  }
}

function displayName(args: Record<string, unknown>) {
  const name = readRequiredString(args, "name");
  if (name.length > 160) throw new Error("名称不能超过 160 个字符。");
  return name;
}

function exactKeys(args: Record<string, unknown>, allowed: readonly string[]) {
  const extra = Object.keys(args).find((key) => !allowed.includes(key));
  if (extra) throw new Error(`当前动作不接受参数：${extra}`);
}

function notifyCreated(project: ToolFolder) {
  publishToolCatalogChange({ kind: "folders", folderId: project.project_id, toolsetId: project.category_id });
  dispatchProjectCatalogChanged();
}
