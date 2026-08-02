import { useState } from "react";

import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import type { ToolMarketTool } from "../model/toolMarket";
import "../../theme-market/ui/theme-install-category-modal.css";

const CALL_NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

export function ToolInstallModal({
  categories, onCancel, onConfirm, selectedCategoryId, tool,
}: {
  categories: readonly ProjectCategory[];
  onCancel: () => void;
  onConfirm: (categoryId: string, callName: string) => void;
  selectedCategoryId: string | null;
  tool: ToolMarketTool;
}) {
  const { t } = useI18n();
  const fallbackCategory = categories.find((item) => item.category_id === selectedCategoryId)
    ?? categories.find((item) => item.is_default)
    ?? categories[0];
  const [categoryId, setCategoryId] = useState(fallbackCategory?.category_id ?? "");
  const [callName, setCallName] = useState(tool.suggestedCallName ?? tool.callName);
  const normalizedCallName = callName.trim();
  const isCallNameValid = CALL_NAME_PATTERN.test(normalizedCallName);

  return (
    <ConfirmModal
      confirmDisabled={!categoryId || !isCallNameValid}
      confirmLabel={t("toolMarket.install.confirm")}
      message={t("toolMarket.install.message", { name: tool.displayName })}
      onCancel={onCancel}
      onConfirm={() => categoryId && isCallNameValid && onConfirm(categoryId, normalizedCallName)}
      title={t("toolMarket.install.title")}
    >
      <div className="confirm-modal__field">
        <span className="confirm-modal__label">{t("toolMarket.install.category")}</span>
        <OptionSelect
          ariaLabel={t("toolMarket.install.category")}
          className="theme-install-category-select"
          disabled={categories.length === 0}
          onChange={setCategoryId}
          options={categories.map((category) => ({
            label: category.name,
            value: category.category_id,
          }))}
          placeholder={t("toolMarket.install.category")}
          value={categoryId}
          variant="integrated-overlay"
        />
      </div>
      <label className="confirm-modal__field tool-install-modal__call-name">
        <span className="confirm-modal__label">{t("toolMarket.install.callName")}</span>
        <input
          aria-invalid={!isCallNameValid}
          autoComplete="off"
          onChange={(event) => setCallName(event.target.value)}
          spellCheck={false}
          value={callName}
        />
        <small>{t(
          tool.installationStatus === "call-name-conflict"
            ? "toolMarket.install.callNameConflict"
            : "toolMarket.install.callNameHint",
        )}</small>
      </label>
    </ConfirmModal>
  );
}
