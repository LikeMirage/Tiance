import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import type { PendingToolFolderDelete } from "./toolFolderContextMenuTypes";

type ToolFolderDeleteConfirmModalProps = {
  deletingFolderId: string | null;
  onCancel: () => void;
  onConfirm: (pendingDelete: NonNullable<PendingToolFolderDelete>) => void;
  pendingDelete: NonNullable<PendingToolFolderDelete>;
};

export function ToolFolderDeleteConfirmModal({
  deletingFolderId,
  onCancel,
  onConfirm,
  pendingDelete,
}: ToolFolderDeleteConfirmModalProps) {
  const isDeleting = deletingFolderId === pendingDelete.folderId;

  return (
    <ConfirmModal
      danger
      confirmDisabled={isDeleting}
      confirmLabel={isDeleting ? "删除中" : "删除"}
      message={`会删除“${pendingDelete.folderName}”的真实文件夹和其中所有文件，删除后无法恢复。`}
      onCancel={onCancel}
      onConfirm={() => onConfirm(pendingDelete)}
      title="删除工具"
    />
  );
}
