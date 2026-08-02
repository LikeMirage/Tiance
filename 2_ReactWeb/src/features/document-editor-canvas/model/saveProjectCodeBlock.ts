import { publishProjectFileMutation } from "../../../entities/project/model/projectFileMutation";
import { saveProjectFileContent } from "../../../services/project/saveProjectFileContent";
import { buildCodeBlockRootFilePath } from "../../markdown-preview/model/codeBlockFile";

export async function saveProjectCodeBlock(projectId: string, code: string, language: string) {
  const filePath = buildCodeBlockRootFilePath(language);
  const node = await saveProjectFileContent(projectId, filePath, code);
  publishProjectFileMutation({ projectId, node });
  return node.path;
}
