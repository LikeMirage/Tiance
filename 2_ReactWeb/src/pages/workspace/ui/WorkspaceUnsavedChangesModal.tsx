import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";

type WorkspaceUnsavedChangesModalProps = {
  modal: {
    confirmLabel: string;
    error: string | null;
    fileLabels: string[];
    isBusy: boolean;
    onCancel: () => void;
    onConfirm: () => void;
    onDiscard: () => void;
    secondaryLabel: string;
    title: string;
  } | null;
};

const MAX_VISIBLE_FILE_LABELS = 8;

export function WorkspaceUnsavedChangesModal({
  modal,
}: WorkspaceUnsavedChangesModalProps) {
  if (!modal) return null;
  const visibleLabels = modal.fileLabels.slice(0, MAX_VISIBLE_FILE_LABELS);
  const hiddenCount = modal.fileLabels.length - visibleLabels.length;
  const message = [
    `有 ${modal.fileLabels.length} 个文件包含未保存的更改：`,
    ...visibleLabels.map((label) => `• ${label}`),
    hiddenCount > 0 ? `• 另外 ${hiddenCount} 个文件` : "",
    modal.error ? `处理失败：${modal.error}` : "",
  ].filter(Boolean).join("\n");

  return (
    <ConfirmModal
      cancelDisabled={modal.isBusy}
      confirmDisabled={modal.isBusy}
      confirmLabel={modal.confirmLabel}
      message={message}
      onCancel={modal.onCancel}
      onConfirm={modal.onConfirm}
      onSecondary={modal.onDiscard}
      secondaryDanger
      secondaryDisabled={modal.isBusy}
      secondaryLabel={modal.secondaryLabel}
      title={modal.title}
    />
  );
}
