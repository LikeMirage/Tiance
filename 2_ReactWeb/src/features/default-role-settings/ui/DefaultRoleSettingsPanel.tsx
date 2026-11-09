import { useEffect } from "react";
import { DEFAULT_ROLE_COLLECTIONS } from "../../../services/project/defaultRoles";
import { useI18n } from "../../../shared/i18n";
import { useDefaultRoles } from "../model/useDefaultRoles";
import { RoleDefaultPicker } from "./RoleDefaultPicker";
import "./default-role-settings.css";

export function DefaultRoleSettingsPanel({ onReady }: { onReady?: () => void }) {
  const { t } = useI18n();
  const state = useDefaultRoles();
  const { catalog, defaults } = state;
  useEffect(() => { if (!state.isLoading) onReady?.(); }, [state.isLoading, onReady]);
  return (
    <section className="default-role-settings" aria-label={t("workspace.settings.defaultRoles")}>
      <h2>{t("workspace.settings.defaultRoles")}</h2>
      <p>{t("defaultRoleSettings.description")}</p>
      {state.error ? <div className="default-role-settings__error" role="status">
        {state.error} <button type="button" onClick={() => void state.load()} disabled={state.isLoading || state.isSaving}>{t("common.actions.retry")}</button>
      </div> : null}
      {state.isLoading && !state.catalog ? <p>{t("common.status.loading")}</p> : null}
      {catalog && defaults ? DEFAULT_ROLE_COLLECTIONS.map(collection => (
        <RoleDefaultPicker key={collection}
          label={t(`defaultRoleSettings.collections.${collection}`)}
          catalog={catalog} selectedRoleProjectId={defaults[collection]}
          disabled={state.isLoading || state.isSaving}
          onSelect={roleId => state.select(collection, roleId)} />
      )) : null}
    </section>
  );
}
