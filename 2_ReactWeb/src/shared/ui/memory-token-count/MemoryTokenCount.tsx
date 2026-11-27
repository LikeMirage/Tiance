import { useI18n } from "../../i18n";

export function MemoryTokenCount({ count, total = false }: { count?: number; total?: boolean }) {
  const { t, language } = useI18n();
  if (count === undefined) return null;
  return (
    <span title={t("aiPanel.memoryDashboard.estimateHint")}>
      {t(total ? "aiPanel.memoryDashboard.totalTokens" : "aiPanel.memoryDashboard.itemTokens", {
        count: count.toLocaleString(language),
      })}
    </span>
  );
}
