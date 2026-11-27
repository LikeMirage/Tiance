import { ChatsCircle, DownloadSimple, GitBranch } from "@phosphor-icons/react";
import { useI18n } from "../../../shared/i18n";

type Props = {
  exportPanelId: string;
  exportOpen: boolean;
  onExport?: () => void;
  onOpenOverview?: () => void;
  onOpenBranches?: () => void;
};

export function ChatConversationActions({ exportPanelId, exportOpen, onExport, onOpenOverview, onOpenBranches }: Props) {
  const { t } = useI18n();
  const exportLabel = t("aiPanel.header.exportConversation");
  return (
    <>
      <button className={`ai-panel__composer-add${exportOpen ? " ai-panel__composer-add--open" : ""}`} type="button" title={exportLabel} aria-label={exportLabel}
        aria-haspopup="dialog" aria-expanded={exportOpen} aria-controls={exportOpen ? exportPanelId : undefined}
        disabled={!onExport} onClick={onExport}>
        <DownloadSimple size={15} weight="regular" aria-hidden="true" />
      </button>
      {[
        { label: t("aiPanel.header.conversationOverview"), Icon: ChatsCircle, action: onOpenOverview },
        { label: t("projectOverview.views.branches"), Icon: GitBranch, action: onOpenBranches },
      ].map(({ label, Icon, action }) => (
        <button
          key={label}
          className="ai-panel__action"
          type="button"
          aria-label={label}
          title={label}
          disabled={!action}
          onClick={action}
        >
          <Icon size={15} weight="regular" aria-hidden="true" />
        </button>
      ))}
    </>
  );
}
