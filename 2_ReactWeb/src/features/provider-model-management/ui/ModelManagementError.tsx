export function ModelManagementError({ message }: { message: string | null }) {
  return message ? (
    <div
      className="provider-canvas__model-empty provider-canvas__model-empty--error"
      role="status"
    >
      {message}
    </div>
  ) : null;
}
