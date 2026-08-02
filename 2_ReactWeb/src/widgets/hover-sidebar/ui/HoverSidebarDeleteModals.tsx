import type { Dispatch, SetStateAction } from "react";

import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";

export type HoverSidebarDeleteTarget = {
  id: string;
  kind?: "project" | "role" | "provider" | "theme";
  label: string;
} | null;

type HoverSidebarDeleteModalsProps = {
  deleteProjectCategory: (categoryId: string) => Promise<void>;
  deleteToolset: (toolsetId: string) => Promise<void>;
  deletingProjectCategoryId: string | null;
  deletingToolsetId: string | null;
  pendingDeleteProjectCategory: HoverSidebarDeleteTarget;
  pendingDeleteToolset: HoverSidebarDeleteTarget;
  setDeletingProjectCategoryId: Dispatch<SetStateAction<string | null>>;
  setDeletingToolsetId: Dispatch<SetStateAction<string | null>>;
  setPendingDeleteProjectCategory: Dispatch<SetStateAction<HoverSidebarDeleteTarget>>;
  setPendingDeleteToolset: Dispatch<SetStateAction<HoverSidebarDeleteTarget>>;
};

export function HoverSidebarDeleteModals({
  deleteProjectCategory,
  deleteToolset,
  deletingProjectCategoryId,
  deletingToolsetId,
  pendingDeleteProjectCategory,
  pendingDeleteToolset,
  setDeletingProjectCategoryId,
  setDeletingToolsetId,
  setPendingDeleteProjectCategory,
  setPendingDeleteToolset,
}: HoverSidebarDeleteModalsProps) {
  const { t } = useI18n();
  return (
    <>
      {pendingDeleteProjectCategory ? (
        <ConfirmModal
          danger
          title={t(
            pendingDeleteProjectCategory.kind === "role"
              ? "sidebar.delete.roleCategoryTitle"
              : pendingDeleteProjectCategory.kind === "theme"
                ? "sidebar.delete.themeCategoryTitle"
                : "sidebar.delete.projectCategoryTitle",
          )}
          message={t(
            pendingDeleteProjectCategory.kind === "role"
              ? "sidebar.delete.roleCategoryMessage"
              : pendingDeleteProjectCategory.kind === "theme"
                ? "sidebar.delete.themeCategoryMessage"
                : "sidebar.delete.projectCategoryMessage",
            {
            label: pendingDeleteProjectCategory.label,
            },
          )}
          confirmDisabled={deletingProjectCategoryId === pendingDeleteProjectCategory.id}
          confirmLabel={deletingProjectCategoryId === pendingDeleteProjectCategory.id ? t("common.actions.deleting") : t("common.actions.delete")}
          onCancel={() => setPendingDeleteProjectCategory(null)}
          onConfirm={() => {
            const category = pendingDeleteProjectCategory;
            setDeletingProjectCategoryId(category.id);
            void deleteProjectCategory(category.id)
              .then(() => {
                setPendingDeleteProjectCategory(null);
              })
              .catch(() => undefined)
              .finally(() => {
                setDeletingProjectCategoryId((current) =>
                  current === category.id ? null : current,
                );
              });
          }}
        />
      ) : null}

      {pendingDeleteToolset ? (
        <ConfirmModal
          danger
          title={t("sidebar.delete.toolsetTitle")}
          message={t("sidebar.delete.toolsetMessage", {
            label: pendingDeleteToolset.label,
          })}
          confirmDisabled={deletingToolsetId === pendingDeleteToolset.id}
          confirmLabel={deletingToolsetId === pendingDeleteToolset.id ? t("common.actions.deleting") : t("common.actions.delete")}
          onCancel={() => setPendingDeleteToolset(null)}
          onConfirm={() => {
            const toolset = pendingDeleteToolset;
            setDeletingToolsetId(toolset.id);
            void deleteToolset(toolset.id)
              .then(() => {
                setPendingDeleteToolset(null);
              })
              .catch(() => undefined)
              .finally(() => {
                setDeletingToolsetId((current) =>
                  current === toolset.id ? null : current,
                );
              });
          }}
        />
      ) : null}
    </>
  );
}
