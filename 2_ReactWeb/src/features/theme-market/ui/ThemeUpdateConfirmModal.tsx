import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import type { ThemeMarketTheme } from "../model/themeMarket";

type ThemeUpdateConfirmModalProps = {
  onCancel: () => void;
  onConfirm: () => void;
  theme: ThemeMarketTheme;
};

export function ThemeUpdateConfirmModal({
  onCancel,
  onConfirm,
  theme,
}: ThemeUpdateConfirmModalProps) {
  const { t } = useI18n();

  return (
    <ConfirmModal
      confirmLabel={t("themeMarket.install.updateConfirm")}
      message={t("themeMarket.install.updateMessage", {
        current: theme.localVersion ?? "-",
        name: theme.name,
        next: theme.version,
      })}
      onCancel={onCancel}
      onConfirm={onConfirm}
      title={t("themeMarket.install.updateTitle")}
    />
  );
}
