import { useCallback, useState } from "react";
import { useI18n } from "../../../shared/i18n";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";
import { TelegramConnectionPanel } from "./TelegramConnectionPanel";
import { TelegramActivityPanel } from "./TelegramActivityPanel";
import { TelegramGuide } from "./TelegramGuide";
import "./telegram-access.css";

const views = ["connection", "logs", "quickStart", "commands", "faq"] as const;
type View = typeof views[number];

export function TelegramAccessPanel() {
  const { t } = useI18n();
  const [view, setView] = useState<View>("connection");
  const [connection, setConnection] = useState<{ id: string | null; name: string }>({ id: null, name: "" });
  const onConnection = useCallback((id: string | null, name: string) => {
    setConnection(previous => previous.id === id && previous.name === name ? previous : { id, name });
  }, []);
  return <div className="telegram-settings">
    <SettingsViewTabs activeView={view} onChange={setView} ariaLabel={t("telegramAccess.tabs.aria")}
      tabs={views.map(id => ({ id, label: t(`telegramAccess.tabs.${id}`) }))} />
    {/* Preserve credential drafts while reading help; poll only on the connection tab. */}
    <div hidden={view !== "connection"} role="tabpanel" aria-label={t("telegramAccess.tabs.connection")}>
      <TelegramConnectionPanel active={view === "connection"} onConnection={onConnection} />
    </div>
    {view === "logs" && <div role="tabpanel" aria-label={t("telegramAccess.tabs.logs")}>
      <TelegramActivityPanel key={connection.id ?? ""} connectionId={connection.id} name={connection.name} />
    </div>}
    {view !== "connection" && view !== "logs" && <div role="tabpanel" aria-label={t(`telegramAccess.tabs.${view}`)}>
      <TelegramGuide tab={view} />
    </div>}
  </div>;
}
