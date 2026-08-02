import { useId, useMemo, useState } from "react";

import type { ConversationRoleCategory } from "../../../entities/role-configuration/model/roleConfiguration";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import {
  OptionSelect,
  type OptionSelectItem,
} from "../../../shared/ui/option-select/OptionSelect";

type Props = {
  categories: ConversationRoleCategory[];
  portalTarget?: HTMLElement;
  saving: boolean;
  onCancel: () => void;
  onSave: (name: string, categoryId: string) => void;
};

export function SaveConversationRoleDialog({
  categories,
  portalTarget,
  saving,
  onCancel,
  onSave,
}: Props) {
  const categoryLabelId = useId();
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState(
    categories[0]?.category_id ?? "",
  );
  const categoryOptions = useMemo<Array<OptionSelectItem<string>>>(
    () => categories.map((category) => ({
      label: category.name,
      value: category.category_id,
    })),
    [categories],
  );

  return (
    <ConfirmModal
      contained={Boolean(portalTarget)}
      title="保存当前角色"
      message="保存当前会话中的角色配置。"
      confirmLabel={saving ? "保存中…" : "保存"}
      confirmDisabled={!name.trim() || !categoryId || saving}
      cancelDisabled={saving}
      onCancel={onCancel}
      onConfirm={() => onSave(name.trim(), categoryId)}
      portalTarget={portalTarget}
    >
      <div className="chat-role-selector__save-fields">
        <label>
          <span>角色名称</span>
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <div className="chat-role-selector__save-field">
          <span id={categoryLabelId}>角色分类</span>
          <OptionSelect
            ariaLabelledBy={categoryLabelId}
            className="chat-role-selector__category-select"
            disabled={saving || categoryOptions.length === 0}
            options={categoryOptions}
            showSelectedOption
            value={categoryId}
            variant="integrated-overlay"
            onChange={setCategoryId}
          />
        </div>
      </div>
    </ConfirmModal>
  );
}
