export function buildSessionKey(projectId: string, sessionId: string) {
  return `${projectId}:${sessionId}`;
}
