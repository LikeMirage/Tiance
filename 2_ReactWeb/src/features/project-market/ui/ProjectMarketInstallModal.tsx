import { useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import type { TranslationKey } from "../../../shared/i18n/locales";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type {
  ProjectMarketNamespace,
  ProjectMarketProject,
} from "../model/projectMarket";
import "./project-market-install-modal.css";

export function ProjectMarketInstallModal({
  categories,
  namespace,
  onCancel,
  onConfirm,
  project,
  selectedCategoryId,
}: {
  categories: readonly ProjectCategory[];
  namespace: ProjectMarketNamespace;
  onCancel: () => void;
  onConfirm: (categoryId: string) => void;
  project: ProjectMarketProject;
  selectedCategoryId: string | null;
}) {
  const { t } = useI18n();
  const fallback = categories.find((category) => category.category_id === selectedCategoryId)
    ?? categories.find((category) => category.is_default)
    ?? categories[0];
  const [categoryId, setCategoryId] = useState(fallback?.category_id ?? "");
  const key = (suffix: string) => `${namespace}.${suffix}` as TranslationKey;

  return (
    <ConfirmModal
      confirmDisabled={!categoryId}
      confirmLabel={t(key("install.confirm"))}
      message={t(key("install.message"), { name: project.name })}
      onCancel={onCancel}
      onConfirm={() => categoryId && onConfirm(categoryId)}
      title={t(key("install.title"))}
    >
      <div className="confirm-modal__field">
        <span className="confirm-modal__label">{t(key("install.category"))}</span>
        <OptionSelect
          ariaLabel={t(key("install.category"))}
          className="project-market-install-select"
          disabled={categories.length === 0}
          onChange={setCategoryId}
          options={categories.map((category) => ({
            label: category.name,
            value: category.category_id,
          }))}
          placeholder={t(key("install.category"))}
          value={categoryId}
          variant="integrated-overlay"
        />
      </div>
    </ConfirmModal>
  );
}
