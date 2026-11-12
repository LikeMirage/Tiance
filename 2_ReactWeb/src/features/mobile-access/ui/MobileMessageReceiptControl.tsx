import { useI18n } from "../../../shared/i18n";
import { AccessSwitchControl } from "../../access-management/ui/AccessSwitchControl";

export function MobileMessageReceiptControl({ id, checked, disabled, onChange }: {
  id: string; checked: boolean; disabled: boolean; onChange: () => void;
}) {
  const { t } = useI18n();
  const label = t("telegramAccess.messageReceipt");
  return <>
    <label htmlFor={id}>{label}</label>
    <div className="telegram-access__connection-control">
      <AccessSwitchControl id={id} label={label} checked={checked} disabled={disabled} onChange={onChange} />
    </div>
  </>;
}
