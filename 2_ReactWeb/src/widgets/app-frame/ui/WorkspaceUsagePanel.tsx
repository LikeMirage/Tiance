import type { WorkspaceStatisticsKind } from "../../../services/workspace/getWorkspaceStatistics";
import { useI18n } from "../../../shared/i18n";
import { formatStatistic } from "../model/statisticFormatting";
import { useWorkspaceUsageSummary } from "../model/useWorkspaceUsageSummary";
import { ConversationCountActions } from "./ConversationCountActions";
import { UsageDailyChart } from "./UsageDailyChart";

type Props = {
  kind: WorkspaceStatisticsKind;
  month: string;
  visible: boolean;
  onMonthChange: (value: string) => void;
  onRequestOpen: () => void;
};

export function WorkspaceUsagePanel({ kind, month, visible, onMonthChange, onRequestOpen }: Props) {
  const { language, t } = useI18n();
  const { data, error, refresh, setConversationTotal } = useWorkspaceUsageSummary(kind, month, visible);
  const duration = kind === "runtime";
  const format = (value: number) => formatStatistic(value, duration, language);
  const totalLabel = kind === "tokens" ? "totalTokens" : duration ? "aiRuntime" : "toolCalls";
  const chartLabel = kind === "tokens" ? "dailyTokens" : duration ? "dailyRuntime" : "dailyTools";
  const rankingLabel = kind === "tokens" ? "mostUsedModels" : duration ? "longestTasks" : "mostUsedTools";
  const emptyRankingLabel = kind === "tokens" ? "noModelUsage" : duration ? "noTaskUsage" : "noToolUsage";
  return <div className={`workspace-usage-panel workspace-usage-panel--${kind}`}>
    <div className="workspace-usage-panel__total">
      <span>{t(`appFrame.metrics.${totalLabel}`)}</span>
      <strong>{data ? format(data.total) : "—"}</strong>
    </div>
    <div className="workspace-usage-panel__month">
      <span>{t("appFrame.metrics.monthTotal")} <b>{data ? format(data.daily.reduce((sum, item) => sum + item.value, 0)) : "—"}</b></span>
      <input type="month" aria-label={t("appFrame.metrics.selectMonth")} value={month}
        min="0001-01" max="9998-12"
        onChange={event => { if (/^\d{4}-\d{2}$/.test(event.target.value)) onMonthChange(event.target.value); }} />
    </div>
    {data ? <UsageDailyChart daily={data.daily} duration={duration} language={language} label={t(`appFrame.metrics.${chartLabel}`)} /> :
      <div className="workspace-usage-panel__placeholder" role="status">{t(error ? "appFrame.metrics.usageReadFailed" : "appFrame.metrics.reading")}</div>}
    {error ? <button type="button" className="workspace-usage-panel__retry" onClick={refresh}>{t("appFrame.metrics.retryStatistics")}</button> : null}
    {data && kind === "tokens" ? <div className="workspace-usage-panel__activity">
      <div className="workspace-usage-panel__row"><span>{t("appFrame.metrics.conversationTotal")}</span><b>{data.conversation_count?.toLocaleString(language)}</b></div>
      <div className="workspace-usage-panel__row"><span>{t("appFrame.metrics.sentMessages")}</span><b>{data.sent_message_count?.toLocaleString(language)}</b></div>
      <ConversationCountActions onConversationCountChange={setConversationTotal} onRequestOpen={onRequestOpen} />
    </div> : null}
    {data ? <section className="workspace-usage-panel__ranking">
      <div className="workspace-usage-panel__ranking-header">
        <span>{t(`appFrame.metrics.${rankingLabel}`)}</span>
        {kind === "tools" ? <small>{t("appFrame.metrics.toolResults", { success: data.success_count ?? 0, failure: data.failure_count ?? 0 })}</small> : null}
      </div>
      {data.ranking.length ? <ol className="workspace-usage-panel__ranking-list">
        {data.ranking.map((item, index) => <li key={item.id} className="workspace-usage-panel__ranking-item">
          <span className="workspace-usage-panel__ranking-position">{index + 1}</span>
          <div className="workspace-usage-panel__ranking-text" title={[item.label || item.id, item.detail].filter(Boolean).join("\n")}>
            <span>{item.label || t("appFrame.metrics.taskIdentifier", { id: item.id })}</span>
            {duration && item.detail ? <small>{item.detail}</small> : null}
          </div>
          <b>{format(item.value)}</b>
        </li>)}
      </ol> : <div className="workspace-usage-panel__ranking-empty">{t(`appFrame.metrics.${emptyRankingLabel}`)}</div>}
    </section> : null}
  </div>;
}
