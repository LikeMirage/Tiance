import { useI18n } from "@/shared/i18n";

import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import type { PendingProjectDelete, ProjectDeleteMode } from "./projectListPanelTypes";
import type { ProjectKind } from "../../../entities/project/model/project";

type ProjectDeleteConfirmModalProps = {
  error?: string | null;
  itemKind?: ProjectKind;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: (pendingDelete: NonNullable<PendingProjectDelete>) => void;
  pendingDelete: NonNullable<PendingProjectDelete>;
};

export function ProjectDeleteConfirmModal({
  error = null,
  itemKind = "project",
  isDeleting,
  onCancel,
  onConfirm,
  pendingDelete,
}: ProjectDeleteConfirmModalProps) {
  const { t } = useI18n();
  const productName = t("common.productName");
  const isBatch = pendingDelete.projectIds.length > 1;

  return (
    <ConfirmModal
      cancelDisabled={isDeleting}
      danger={pendingDelete.mode !== "remove"}
      title={
        itemKind === "role"
          ? t(isBatch ? "roleDelete.batchTitle" : "roleDelete.title")
          : getProjectDeleteDialogTitle(pendingDelete.mode, isBatch, t)
      }
      message={error ?? (
        itemKind === "role"
          ? t(isBatch ? "roleDelete.batchMessage" : "roleDelete.message", {
              count: pendingDelete.projectIds.length,
            })
          : getProjectDeleteDialogMessage(pendingDelete, t, productName)
      )}
      confirmDisabled={isDeleting || Boolean(error)}
      confirmLabel={
        isDeleting
          ? pendingDelete.mode === "remove"
            ? t("projectDelete.confirm.removing")
            : t("projectDelete.confirm.deleting")
          : getProjectDeleteConfirmLabel(pendingDelete.mode, t)
      }
      onCancel={onCancel}
      onConfirm={() => onConfirm(pendingDelete)}
    />
  );
}

type Translate = ReturnType<typeof useI18n>["t"];

function getProjectDeleteDialogTitle(
  mode: ProjectDeleteMode,
  isBatch: boolean,
  t: Translate,
) {
  if (isBatch) {
    if (mode === "delete-local") return t("projectDelete.batch.title.deleteLocal");
    if (mode === "remove") return t("projectDelete.batch.title.remove");
    return t("projectDelete.batch.title.delete");
  }
  if (mode === "delete-local") return t("projectDelete.title.deleteLocal");
  return mode === "remove" ? t("projectDelete.title.remove") : t("projectDelete.title.delete");
}

function getProjectDeleteDialogMessage(
  pendingDelete: NonNullable<PendingProjectDelete>,
  t: Translate,
  productName: string,
) {
  const count = pendingDelete.projectIds.length;
  if (count > 1) {
    if (pendingDelete.mode === "remove") {
      return t("projectDelete.batch.message.remove", { count, productName });
    }
    if (pendingDelete.mode === "delete-local") {
      return t("projectDelete.batch.message.deleteLocal", { count, productName });
    }
    if (pendingDelete.mode === "mixed") {
      return t("projectDelete.batch.message.mixed", { count, productName });
    }
    return t("projectDelete.batch.message.delete", { count });
  }
  const projectName = pendingDelete.projectNames[0] ?? "";
  if (pendingDelete.mode === "remove") {
    return t("projectDelete.message.remove", {
      productName,
      projectName,
    });
  }
  if (pendingDelete.mode === "delete-local") {
    return t("projectDelete.message.deleteLocal", {
      productName,
      projectName,
    });
  }
  return t("projectDelete.message.delete");
}

function getProjectDeleteConfirmLabel(mode: ProjectDeleteMode, t: Translate) {
  if (mode === "remove") return t("projectDelete.confirm.remove");
  if (mode === "delete-local") return t("projectDelete.confirm.deleteLocal");
  return t("projectDelete.confirm.delete");
}
