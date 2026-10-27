import type { ProjectFileRevealRequest } from "../../entities/project/model/project";
import { revealInFileExplorer } from "../desktop/fileExplorer";

export function revealProjectFile(projectId: string, payload: ProjectFileRevealRequest) {
  return revealInFileExplorer(
    `/api/projects/${encodeURIComponent(projectId)}/files/reveal`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
