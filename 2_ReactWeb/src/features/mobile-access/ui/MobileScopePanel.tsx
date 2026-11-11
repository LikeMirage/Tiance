import { useId } from "react";
import type { ProjectKind } from "@/entities/project/model/project";
import { useI18n } from "@/shared/i18n";
import { AccessSwitchControl } from "@/features/access-management/ui/AccessSwitchControl";

const collections: ProjectKind[] = ["project", "tool", "knowledge", "experience", "role", "provider", "theme"];

export function MobileScopePanel({ allowed, disabled, connected, onChange }: {
  allowed: ProjectKind[];
  disabled: boolean;
  connected: boolean;
  onChange: (allowed: ProjectKind[]) => void;
}) {
  const { t } = useI18n();
  const titleId = useId();
  return <section className="telegram-access__scope" aria-labelledby={titleId}>
    <h3 id={titleId}>{t("telegramAccess.scope.title")}</h3>
    {collections.map(kind => <div className="telegram-access__scope-row" key={kind}>
      <span>{t(`telegramAccess.scope.collections.${kind}`)}</span>
      <AccessSwitchControl checked={allowed.includes(kind)} disabled={disabled || !connected}
        label={`${t("telegramAccess.scope.title")} · ${t(`telegramAccess.scope.collections.${kind}`)}`}
        onChange={() => onChange(collections.filter(item => item === kind ? !allowed.includes(item) : allowed.includes(item)))} />
    </div>)}
    {(!connected || allowed.length === 0) && <p className="telegram-access__scope-summary" aria-live="polite">
      {t(!connected ? "telegramAccess.scope.connectFirst" : "telegramAccess.scope.empty")}
    </p>}
  </section>;
}
