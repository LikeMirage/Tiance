import type { Project } from "../../../entities/project/model/project";
import { createRoleProject } from "../../../services/project/createRoleProject";
import { loadRoleConfiguration } from "../../../services/project/roleConfigurationFiles";
import { initializeProjectFiles } from "../../../services/project/initializeProjectFiles";
import { fetchJson } from "../../../services/http/httpClient";
import type { ClientToolRegistration } from "./clientToolBridge";
import { clientToolFailure, clientToolSuccess, parseClientToolArguments, readRequiredString } from "./conversationClientToolValues";
import { collectionManagementAction, notifyCollectionChanged, requireCollectionProject } from "./collectionManagementActions";
import { loadToolProjectScaffold } from "./toolProjectScaffold";

export function createRoleProjectClientToolRegistration(): ClientToolRegistration {
  return { capability: { name: "role.projects", version: 1 }, execute: async (request, { signal }) => {
    let project: Project | null = null;
    let creating = false;
    let action = "";
    try {
      signal.throwIfAborted();
      const args = parseClientToolArguments(request.arguments);
      action = readRequiredString(args, "action");
      const callerId = readRequiredString(request, "project_id");
      const toolId = readRequiredString(request, "tool_project_id");
      const common = await collectionManagementAction("role", action, args, callerId, toolId);
      if (common !== undefined) return clientToolSuccess(common);
      if (action === "get") {
        project = await requireCollectionProject("role", readRequiredString(args, "project_id"));
        const configuration = await loadRoleConfiguration(project.project_id);
        return clientToolSuccess({ action, project, ...configuration,
          effective_configuration: await fetchJson(`/api/projects/roles/${encodeURIComponent(project.project_id)}/configuration`) });
      }
      if (!["create_role", "initialize_current"].includes(action)) throw new Error(`不支持的动作：${action}`);
      const scaffold = await loadToolProjectScaffold(toolId, signal, "role");
      signal.throwIfAborted();
      if (action === "initialize_current") project = await requireCollectionProject("role", callerId);
      else {
        creating = true;
        project = await createRoleProject({ name: readRequiredString(args, "name"), category_id: readRequiredString(args, "category_id") });
        notifyCollectionChanged("role");
      }
      const result = await initializeProjectFiles(project.project_id, "role", scaffold.files);
      notifyCollectionChanged("role");
      return clientToolSuccess({ action, project, ...result,
        documentation_path: `${result.root_path}/${scaffold.documentation}`,
        guidance: "先读取制作说明。已有配置原样保留；新角色沿用平台的默认角色初始化流程。按说明编辑八份配置文件，修改角色模板不会回写既有会话。" });
    } catch (error) {
      return clientToolFailure(error, { action, project, creation_outcome_unknown: creating && !project,
        guidance: "若已创建角色，请在返回项目内继续补齐；创建结果未知时先 list 核对，避免重复创建。" });
    }
  } };
}
