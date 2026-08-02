import { useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { RoleMarketRole } from "../model/roleMarket";
import "../../theme-market/ui/theme-install-category-modal.css";

type RoleInstallCategoryModalProps = {
  categories: readonly ProjectCategory[];
  onCancel: () => void;
  onConfirm: (categoryId: string) => void;
  role: RoleMarketRole;
  selectedCategoryId: string | null;
};

export function RoleInstallCategoryModal({
  categories,
  onCancel,
  onConfirm,
  role,
  selectedCategoryId,
}: RoleInstallCategoryModalProps) {
  const { t } = useI18n();
  const fallbackCategory = categories.find((category) => category.category_id === selectedCategoryId)
    ?? categories.find((category) => category.is_default)
    ?? categories[0];
  const [categoryId, setCategoryId] = useState(fallbackCategory?.category_id ?? "");

  return (
    <ConfirmModal
      confirmDisabled={!categoryId}
      confirmLabel={t("roleMarket.install.confirm")}
      message={t("roleMarket.install.message", { name: role.name })}
      onCancel={onCancel}
      onConfirm={() => categoryId && onConfirm(categoryId)}
      title={t("roleMarket.install.title")}
    >
      <div className="confirm-modal__field">
        <span className="confirm-modal__label">{t("roleMarket.install.category")}</span>
        <OptionSelect
          ariaLabel={t("roleMarket.install.category")}
          className="theme-install-category-select"
          disabled={categories.length === 0}
          onChange={setCategoryId}
          options={categories.map((category) => ({
            label: category.name,
            value: category.category_id,
          }))}
          placeholder={t("roleMarket.install.category")}
          value={categoryId}
          variant="integrated-overlay"
        />
      </div>
    </ConfirmModal>
  );
}
