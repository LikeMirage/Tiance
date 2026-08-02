import { useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { ProviderMarketProvider } from "../model/providerMarket";
import "../../theme-market/ui/theme-install-category-modal.css";

export function ProviderInstallCategoryModal({
  categories,
  onCancel,
  onConfirm,
  provider,
  selectedCategoryId,
}: {
  categories: readonly ProjectCategory[];
  onCancel: () => void;
  onConfirm: (categoryId: string) => void;
  provider: ProviderMarketProvider;
  selectedCategoryId: string | null;
}) {
  const { t } = useI18n();
  const fallbackCategory = categories.find((item) => item.category_id === selectedCategoryId)
    ?? categories.find((item) => item.is_default)
    ?? categories[0];
  const [categoryId, setCategoryId] = useState(fallbackCategory?.category_id ?? "");

  return (
    <ConfirmModal
      confirmDisabled={!categoryId}
      confirmLabel={t("providerMarket.install.confirm")}
      message={t("providerMarket.install.message", { name: provider.name })}
      onCancel={onCancel}
      onConfirm={() => categoryId && onConfirm(categoryId)}
      title={t("providerMarket.install.title")}
    >
      <div className="confirm-modal__field">
        <span className="confirm-modal__label">{t("providerMarket.install.category")}</span>
        <OptionSelect
          ariaLabel={t("providerMarket.install.category")}
          className="theme-install-category-select"
          disabled={categories.length === 0}
          onChange={setCategoryId}
          options={categories.map((category) => ({
            label: category.name,
            value: category.category_id,
          }))}
          placeholder={t("providerMarket.install.category")}
          value={categoryId}
          variant="integrated-overlay"
        />
      </div>
    </ConfirmModal>
  );
}
