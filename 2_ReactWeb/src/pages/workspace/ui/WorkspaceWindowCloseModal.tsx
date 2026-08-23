import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";

type WorkspaceWindowCloseModalProps = {
  error: string | null;
  isBusy: boolean;
  isOpen: boolean;
  onCancel: () => void;
  onExit: () => void;
  onHideToTray: () => void;
};

export function WorkspaceWindowCloseModal({
  error,
  isBusy,
  isOpen,
  onCancel,
  onExit,
  onHideToTray,
}: WorkspaceWindowCloseModalProps) {
  const { t } = useI18n();
  if (!isOpen) return null;

  return (
    <ConfirmModal
      cancelDisabled={isBusy}
      confirmDisabled={isBusy}
      confirmLabel={t("common.windowClosePrompt.hideToTray")}
      message={error ?? t("common.windowClosePrompt.message")}
      onCancel={onCancel}
      onConfirm={onHideToTray}
      onSecondary={onExit}
      secondaryDanger
      secondaryDisabled={isBusy}
      secondaryLabel={t("common.windowClosePrompt.exit")}
      title={t("common.windowClosePrompt.title")}
    />
  );
}
