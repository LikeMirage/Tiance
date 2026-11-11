import type { ToolFolder } from "../../../entities/tool/model/toolset";
import { createToolFolder } from "../../../services/tools/createToolFolder";
import { getToolsets } from "../../../services/tools/getToolsets";
import { updateToolFolderRuntimeSettings } from "../../../services/tools/updateToolFolderRuntimeSettings";
import { getProjectFileContent } from "../../../services/project/getProjectFileContent";
import { initializeProjectFiles } from "../../../services/project/initializeProjectFiles";
import type { ClientToolRegistration } from "./clientToolBridge";
import { clientToolFailure, clientToolSuccess, parseClientToolArguments, readRequiredString } from "./conversationClientToolValues";
import { instantiateToolProjectScaffold, loadToolProjectScaffold } from "./toolProjectScaffold";
import { collectionManagementAction, notifyCollectionChanged, requireCollectionProject } from "./collectionManagementActions";

export const TOOL_PROJECT_CAPABILITY = Object.freeze({ name: "tool.projects", version: 2 });
export function createToolProjectClientToolRegistration(): ClientToolRegistration {
  return { capability: TOOL_PROJECT_CAPABILITY, execute: executeToolProjectAction };
}
async function executeToolProjectAction(
  request: Parameters<ClientToolRegistration["execute"]>[0],
  { signal }: Parameters<ClientToolRegistration["execute"]>[1],
) {
  let action = "";
  let project: ToolFolder | null = null;
  let creating = false;
  try {
    signal.throwIfAborted();
    const args = parseClientToolArguments(request.arguments);
    action = readRequiredString(args, "action");
    const callerId = readRequiredString(request, "project_id");
    const toolId = readRequiredString(request, "tool_project_id");
    const common = await collectionManagementAction("tool", action, args, callerId, toolId);
    if (common !== undefined) return clientToolSuccess(common);
    if (action === "get" || action === "set_state") {
      const target = await requireCollectionProject("tool", readRequiredString(args, "project_id"));
      if (action === "get") {
        const file = await getProjectFileContent(target.project_id, ".tool/tool.json", { signal });
        return clientToolSuccess({ action, project: target, configuration: JSON.parse(file.content) });
      }
      if (!["enabled", "dynamic", "parallel"].some((key) => typeof args[key] === "boolean")) {
        throw new Error("至少提供一个工具开关。");
      }
      const updated = await updateToolFolderRuntimeSettings(target.category_id, target.project_id, {
        ...(typeof args.enabled === "boolean" ? { enabled: args.enabled } : {}),
        ...(typeof args.dynamic === "boolean" ? { dynamic: args.dynamic } : {}),
        ...(typeof args.parallel === "boolean" ? { parallel: args.parallel } : {}),
      });
      notifyCollectionChanged("tool");
      return clientToolSuccess({ action, ...updated });
    }
    if (!["create_tool", "initialize_current"].includes(action)) throw new Error(`不支持的动作：${action}`);
    const explicitCallName = args.call_name === undefined ? null : readRequiredString(args, "call_name");
    if (explicitCallName !== null && !/^[a-z][a-z0-9_]{0,63}$/.test(explicitCallName)) {
      throw new Error("call_name 须为 1–64 位小写英文、数字或下划线，并以小写英文开头。");
    }
    const scaffold = await loadToolProjectScaffold(toolId, signal);
    signal.throwIfAborted();
    if (action === "initialize_current") {
      project = await requireCollectionProject("tool", callerId);
    } else {
      const categoryId = readRequiredString(args, "category_id");
      const category = (await getToolsets()).items.find((item) => item.category_id === categoryId);
      if (!category || category.readonly) throw new Error("工具分类不存在或不可写。");
      creating = true;
      project = await createToolFolder(categoryId, { name: readRequiredString(args, "name") });
      notifyCollectionChanged("tool");
    }
    const callName = explicitCallName ?? `tool_${project.project_id.replaceAll("-", "")}`;
    const files = instantiateToolProjectScaffold(scaffold, project.name, callName);
    const result = await initializeProjectFiles(project.project_id, "tool", files);
    notifyCollectionChanged("tool");
    const root = result.root_path.replaceAll("\\", "/");
    const manifest = JSON.parse((await getProjectFileContent(project.project_id, ".tool/tool.json")).content);
    return clientToolSuccess({
      action, project, ...result, call_name: manifest.name, enabled: manifest.state?.enabled === true,
      template_version: scaffold.version, documentation_path: `${root}/${scaffold.documentation}`,
      manifest_path: `${root}/.tool/tool.json`,
      guidance: [
        `制作前先读取 ${root}/${scaffold.documentation}，再按索引阅读参数、权限、能力桥和测试资料。`,
        "本次仅补齐缺失文件，已有文件原样保留。新模板默认关闭；已有工具的开关不变。",
        "制作并验证完成后，按用户意愿使用 set_state 开启，或修改 .tool/tool.json 的 state.enabled；目标会话还需允许使用该工具。",
      ],
    });
  } catch (error) {
    return clientToolFailure(error, { action, project,
      status: project ? "inspect_existing_project" : creating ? "creation_outcome_unknown" : "failed",
      guidance: "若已创建项目，在返回的项目内继续初始化。若创建响应丢失，先 list 核对，避免重复创建。初始化只补缺失文件，不覆盖现有内容。",
    });
  }
}
