import { useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { ThemeMarketTheme } from "../model/themeMarket";
import "./theme-install-category-modal.css";

type ThemeInstallCategoryModalProps = {
  categories: readonly ProjectCategory[];
  onCancel: () => void;
  onConfirm: (categoryId: string) => void;
  selectedCategoryId: string | null;
  theme: ThemeMarketTheme;
};

export function ThemeInstallCategoryModal({
  categories,
  onCancel,
  onConfirm,
  selectedCategoryId,
  theme,
}: ThemeInstallCategoryModalProps) {
  const { t } = useI18n();
  const fallbackCategory = categories.find((category) => category.category_id === selectedCategoryId)
    ?? categories.find((category) => category.is_default)
    ?? categories[0];
  const [categoryId, setCategoryId] = useState(fallbackCategory?.category_id ?? "");

  return (
    <ConfirmModal
      confirmDisabled={!categoryId}
      confirmLabel={t("themeMarket.install.confirm")}
      message={t("themeMarket.install.message", { name: theme.name })}
      onCancel={onCancel}
      onConfirm={() => categoryId && onConfirm(categoryId)}
      title={t("themeMarket.install.title")}
    >
      <div className="confirm-modal__field">
        <span className="confirm-modal__label">{t("themeMarket.install.category")}</span>
        <OptionSelect
          ariaLabel={t("themeMarket.install.category")}
          className="theme-install-category-select"
          disabled={categories.length === 0}
          onChange={setCategoryId}
          options={categories.map((category) => ({
            label: category.name,
            value: category.category_id,
          }))}
          placeholder={t("themeMarket.install.category")}
          value={categoryId}
          variant="integrated-overlay"
        />
      </div>
    </ConfirmModal>
  );
}
