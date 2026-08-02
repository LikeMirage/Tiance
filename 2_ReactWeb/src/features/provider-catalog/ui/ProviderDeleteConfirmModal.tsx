import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import type { PendingProviderDelete } from "./ProviderCatalogContextMenu";

type ProviderDeleteConfirmModalProps = {
  deletingProviderId: string | null;
  onCancel: () => void;
  onConfirm: (pendingDelete: PendingProviderDelete) => void;
  pendingDelete: PendingProviderDelete;
};

export function ProviderDeleteConfirmModal({
  deletingProviderId,
  onCancel,
  onConfirm,
  pendingDelete,
}: ProviderDeleteConfirmModalProps) {
  const { t } = useI18n();
  const isDeleting = deletingProviderId === pendingDelete.providerId;

  return (
    <ConfirmModal
      danger
      confirmDisabled={isDeleting}
      confirmLabel={
        isDeleting
          ? t("providerCatalog.deleteConfirm.deleting")
          : t("common.actions.delete")
      }
      message={t("providerCatalog.deleteConfirm.message", {
        provider: pendingDelete.providerName,
      })}
      title={t("providerCatalog.deleteConfirm.title")}
      onCancel={onCancel}
      onConfirm={() => onConfirm(pendingDelete)}
    />
  );
}
