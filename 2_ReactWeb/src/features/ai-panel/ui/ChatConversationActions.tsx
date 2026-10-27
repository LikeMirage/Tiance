import { ChatsCircle, DownloadSimple, GitBranch } from "@phosphor-icons/react";
import { useI18n } from "../../../shared/i18n";

type Props = {
  onExport?: () => void;
  onOpenOverview?: () => void;
  onOpenBranches?: () => void;
};

export function ChatConversationActions({ onExport, onOpenOverview, onOpenBranches }: Props) {
  const { t } = useI18n();
  return (
    <>
      {[
        { label: t("aiPanel.header.exportConversation"), Icon: DownloadSimple, action: onExport },
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
