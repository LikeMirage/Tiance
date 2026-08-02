import type { Project } from "../../../entities/project/model/project";
import type { ProjectImportConflict } from "./projectCatalogHelpers";

export type ProjectFolderImportBatchFailure = {
  error: unknown;
  rootPath: string;
};

export type ProjectFolderImportBatchResult = {
  conflicts: ProjectImportConflict[];
  createdProjects: Project[];
  failures: ProjectFolderImportBatchFailure[];
};

export async function runProjectFolderImportBatch(
  rootPaths: string[],
  createProject: (rootPath: string) => Promise<Project>,
  parseConflict: (error: unknown) => ProjectImportConflict | null,
): Promise<ProjectFolderImportBatchResult> {
  const result: ProjectFolderImportBatchResult = {
    conflicts: [],
    createdProjects: [],
    failures: [],
  };

  for (const rootPath of uniqueNonEmptyPaths(rootPaths)) {
    try {
      result.createdProjects.push(await createProject(rootPath));
    } catch (error) {
      const conflict = parseConflict(error);
      if (conflict) {
        result.conflicts.push(conflict);
      } else {
        result.failures.push({ error, rootPath });
      }
    }
  }

  return result;
}

function uniqueNonEmptyPaths(rootPaths: string[]) {
  const uniquePaths = new Set<string>();
  for (const rootPath of rootPaths) {
    const normalizedPath = rootPath.trim();
    if (normalizedPath) uniquePaths.add(normalizedPath);
  }
  return [...uniquePaths];
}
