import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import type { RoleMarketRole } from "../model/roleMarket";

type RoleUpdateConfirmModalProps = {
  onCancel: () => void;
  onConfirm: () => void;
  role: RoleMarketRole;
};

export function RoleUpdateConfirmModal({
  onCancel,
  onConfirm,
  role,
}: RoleUpdateConfirmModalProps) {
  const { t } = useI18n();

  return (
    <ConfirmModal
      confirmLabel={t("roleMarket.install.updateConfirm")}
      message={t("roleMarket.install.updateMessage", {
        current: role.localVersion ?? "-",
        name: role.name,
        next: role.version,
      })}
      onCancel={onCancel}
      onConfirm={onConfirm}
      title={t("roleMarket.install.updateTitle")}
    />
  );
}
