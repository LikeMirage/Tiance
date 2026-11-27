import { Fragment } from "react";
import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import { useI18n } from "../../../shared/i18n";
import { formatCacheHitRate, formatCostAmount, formatTokenCount } from "../../../shared/model/usageFormatting";
import { Tooltip } from "../../../shared/ui/tooltip";

function totalTokens(usage: ChatUsage) {
  return usage.total_tokens ?? (usage.prompt_tokens != null && usage.completion_tokens != null
    ? usage.prompt_tokens + usage.completion_tokens : null);
}

export function ReplyUsage({ usage }: { usage: ChatUsage }) {
  const total = totalTokens(usage);
  return (
    <span className="chat-msg__reply-usage">
      <Tooltip focusable content={<ReplyUsageDetails usage={usage} />} maxWidth={240}>
        Tokens {total == null ? "—" : formatTokenCount(total)}
      </Tooltip>
    </span>
  );
}

function ReplyUsageDetails({ usage }: { usage: ChatUsage }) {
  const { t, language } = useI18n();
  const estimated = usage.estimated_fields ?? [];
  const count = (field: keyof ChatUsage, value: number | null | undefined) =>
    value == null ? "—" : (estimated.includes(field) ? "≈" : "") + formatTokenCount(value);
  const seconds = usage.output_duration_seconds;
  const output = usage.completion_tokens;
  const speed = seconds != null && seconds > 0 && output != null && output > 0
    ? (estimated.includes("completion_tokens") ? "≈" : "") + (output / seconds).toFixed(1) + " t/s" : "—";
  const estimatedCost = usage.cost_at_current_rates || estimated.some((field) =>
    ["prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"].includes(field));
  const rows = [
    [t("aiPanel.usage.total"), count("total_tokens", totalTokens(usage))],
    [t("aiPanel.usage.speed"), speed],
    [t("aiPanel.usage.input"), count("prompt_tokens", usage.prompt_tokens)],
    [t("aiPanel.usage.output"), count("completion_tokens", output)],
    [t("aiPanel.usage.cacheHit"), count("prompt_cache_hit_tokens", usage.prompt_cache_hit_tokens)],
    [t("aiPanel.usage.cacheHitRate"), formatCacheHitRate(usage, language)],
    [t("aiPanel.usage.cacheMiss"), count("prompt_cache_miss_tokens", usage.prompt_cache_miss_tokens)],
    [t(usage.cost_at_current_rates ? "aiPanel.usage.costAtCurrentRates" : "aiPanel.usage.cost"),
      usage.cost_amount == null ? "—" : (estimatedCost ? "≈" : "") + formatCostAmount(usage)],
  ];
  return <span className="chat-msg__usage-details">{rows.map(([label, value]) =>
    <Fragment key={label}><span>{label}</span><span>{value}</span></Fragment>,
  )}</span>;
}
