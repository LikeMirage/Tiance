import { useCallback, useState } from "react";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";
import { useI18n } from "../../../shared/i18n";
import { TelegramActivityPanel } from "./TelegramActivityPanel";
import { PlatformConnectionPanel, type Platform } from "./PlatformConnectionPanel";
import { PlatformGuide } from "./PlatformGuide";
import "./telegram-access.css";

const views = ["connection", "logs", "quickStart", "commands", "faq"] as const;
export function PlatformAccessPanel({ platform }: { platform: Platform }) {
  const { t } = useI18n();
  const [view, setView] = useState<typeof views[number]>("connection");
  const [connection, setConnection] = useState({ id: null as string | null, name: "" });
  const selected = useCallback((id: string | null, name: string) => {
    setConnection(old => old.id === id && old.name === name ? old : { id, name });
  }, []);
  return <div className="telegram-settings">
    <SettingsViewTabs activeView={view} onChange={setView} ariaLabel={platform}
      tabs={views.map(id => ({ id, label: t(`telegramAccess.tabs.${id}`) }))} />
    <div hidden={view !== "connection"} role="tabpanel">
      <PlatformConnectionPanel platform={platform} active={view === "connection"} onConnection={selected} />
    </div>
    {view === "logs" && <TelegramActivityPanel key={connection.id ?? platform} platform={platform} connectionId={connection.id} name={connection.name} />}
    {view !== "connection" && view !== "logs" && <PlatformGuide platform={platform} tab={view} />}
  </div>;
}
