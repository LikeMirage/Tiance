import { useI18n, type TranslationKey } from "../../../shared/i18n";

export type ConversationDataFileName =
  | "compressions.jsonl"
  | "injection_preview.json"
  | "messages.jsonl"
  | "session.json"
  | "index.json"
  | "project_memory.jsonl"
  | "global_memory.jsonl";

type ConversationDataDashboardItem = {
  descriptionKey: TranslationKey;
  fileName: ConversationDataFileName;
  titleKey: TranslationKey;
};

const CONVERSATION_DATA_DASHBOARDS: ConversationDataDashboardItem[] = [
  {
    descriptionKey: "aiPanel.dataDashboard.items.compressions.description",
    fileName: "compressions.jsonl",
    titleKey: "aiPanel.dataDashboard.items.compressions.title",
  },
  {
    descriptionKey: "aiPanel.dataDashboard.items.injectionPreview.description",
    fileName: "injection_preview.json",
    titleKey: "aiPanel.dataDashboard.items.injectionPreview.title",
  },
  {
    descriptionKey: "aiPanel.dataDashboard.items.messages.description",
    fileName: "messages.jsonl",
    titleKey: "aiPanel.dataDashboard.items.messages.title",
  },
  {
    descriptionKey: "aiPanel.dataDashboard.items.session.description",
    fileName: "session.json",
    titleKey: "aiPanel.dataDashboard.items.session.title",
  },
  {
    descriptionKey: "aiPanel.dataDashboard.items.index.description",
    fileName: "index.json",
    titleKey: "aiPanel.dataDashboard.items.index.title",
  },
  {
    descriptionKey: "aiPanel.dataDashboard.items.projectMemory.description",
    fileName: "project_memory.jsonl",
    titleKey: "aiPanel.dataDashboard.items.projectMemory.title",
  },
  {
    descriptionKey: "aiPanel.dataDashboard.items.globalMemory.description",
    fileName: "global_memory.jsonl",
    titleKey: "aiPanel.dataDashboard.items.globalMemory.title",
  },
];

export function ChatDataDashboardPanel({
  activeFileName,
  onOpenDataFile,
}: {
  activeFileName?: ConversationDataFileName | null;
  onOpenDataFile?: (fileName: ConversationDataFileName) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="ai-panel__settings">
      <div className="ai-panel__setting-group">
        <span className="ai-panel__setting-group-title">{t("aiPanel.dataDashboard.title")}</span>
        <div className="ai-panel__data-dashboard-list">
          {CONVERSATION_DATA_DASHBOARDS.map((item) => {
            const isActive = item.fileName === activeFileName;
            return (
              <button
                className={isActive
                  ? "ai-panel__data-dashboard-card ai-panel__data-dashboard-card--active"
                  : "ai-panel__data-dashboard-card"}
                type="button"
                key={item.fileName}
                aria-current={isActive ? "page" : undefined}
                disabled={!onOpenDataFile}
                onClick={() => onOpenDataFile?.(item.fileName)}
              >
                <span>
                  <strong>{t(item.titleKey)}</strong>
                  <small>{item.fileName}</small>
                </span>
                <p>{t(item.descriptionKey)}</p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
