export type ProjectBatchActionResult = {
  completedProjectIds: string[];
  error: unknown | null;
  remainingProjectIds: string[];
};

export async function runSequentialProjectBatchAction(
  projectIds: string[],
  action: (projectId: string) => Promise<void>,
): Promise<ProjectBatchActionResult> {
  for (let index = 0; index < projectIds.length; index += 1) {
    try {
      await action(projectIds[index]);
    } catch (error) {
      return {
        completedProjectIds: projectIds.slice(0, index),
        error,
        remainingProjectIds: projectIds.slice(index),
      };
    }
  }

  return {
    completedProjectIds: projectIds,
    error: null,
    remainingProjectIds: [],
  };
}
