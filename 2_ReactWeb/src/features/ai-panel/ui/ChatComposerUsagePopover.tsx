import { useId } from "react";
import { EmbeddedPanel } from "../../../shared/ui/embedded-panel/EmbeddedPanel";
import { WarningCircle } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import { Tooltip } from "../../../shared/ui/tooltip";
import {
  formatCostAmount,
  formatTokenCount,
  type UsageDisplaySummary,
} from "../model/usageSummary";
import type { ChatComposerUsageState } from "./ChatComposerTypes";

export function ChatUsagePopover({ usage, isOpen, onOpenChange, panelContainer }: {
  usage: ChatComposerUsageState;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  panelContainer: HTMLElement | null;
}) {
  const { t } = useI18n();
  const panelId = useId();
  return <div className="ai-panel__usage-area">
    <button className="ai-panel__usage-trigger" type="button" aria-label={t("aiPanel.usage.aria")}
      aria-expanded={isOpen} aria-controls={isOpen ? panelId : undefined}
      onClick={() => onOpenChange(!isOpen)}>
      {usage.contextTokens === null ? "--" : formatTokenCount(usage.contextTokens)}
    </button>
    {isOpen ? <EmbeddedPanel container={panelContainer} id={panelId}
      ariaLabel={t("aiPanel.usage.aria")} className="ai-panel__usage-panel"
      onClose={() => onOpenChange(false)} title={
        <span className="ai-panel__usage-popover-title">
          <span>{t("aiPanel.usage.title")}</span>
          {(usage.selected?.estimated_record_count ?? 0) > 0 ? (
            <UsageEstimateWarning
              label={t("aiPanel.usage.totalEstimated")}
            />
          ) : null}
        </span>
      } headerContent={
        <div className="ai-panel__usage-context">
          <span>{t("aiPanel.usage.context")}</span>
          <strong>
            {usage.contextTokens === null ? "--" : formatTokenCount(usage.contextTokens)}
          </strong>
          {usage.contextTokensEstimated ? (
            <UsageEstimateWarning
              label={t("aiPanel.usage.contextEstimated")}
            />
          ) : null}
        </div>
      }>
      <div className="ai-panel__usage-layout">
        <div
          className="ai-panel__usage-scope-list"
          role="listbox"
          aria-label={t("aiPanel.usage.scope")}
        >
          {usage.scopeOptions.map((option) => (
            <button
              key={option.value}
              className="ai-panel__usage-scope-option"
              type="button"
              role="option"
              aria-selected={option.value === usage.scopeKey}
              onClick={() => usage.onSelectScope(option.value)}
            >
              <span className="ai-panel__usage-scope-option-main">
                <span className="ai-panel__usage-scope-option-label">
                  {option.label}
                </span>
              </span>
              {option.providerLabel ? (
                <span className="ai-panel__usage-scope-option-provider">
                  {option.providerLabel}
                </span>
              ) : null}
            </button>
          ))}
        </div>
        <UsageMetricGrid selectedUsage={usage.selected} />
      </div>
    </EmbeddedPanel> : null}
  </div>;
}

function UsageEstimateWarning({ label }: { label: string }) {
  return (
    <Tooltip content={label} maxWidth={320}>
      <span
        className="ai-panel__usage-estimate-warning"
        aria-label={label}
        role="img"
        tabIndex={0}
      >
        <WarningCircle aria-hidden="true" size={12} weight="fill" />
      </span>
    </Tooltip>
  );
}

function UsageMetricGrid({
  selectedUsage,
}: {
  selectedUsage: UsageDisplaySummary | undefined;
}) {
  const { t } = useI18n();
  return (
    <dl className="ai-panel__usage-grid">
      <div>
        <dt>{t("aiPanel.usage.total")}</dt>
        <dd>{formatTokenCount(selectedUsage?.total_tokens)}</dd>
      </div>
      <div>
        <dt>{t("aiPanel.usage.input")}</dt>
        <dd>{formatTokenCount(selectedUsage?.prompt_tokens)}</dd>
      </div>
      <div>
        <dt>{t("aiPanel.usage.output")}</dt>
        <dd>{formatTokenCount(selectedUsage?.completion_tokens)}</dd>
      </div>
      <div>
        <dt>{t("aiPanel.usage.reasoning")}</dt>
        <dd>{formatTokenCount(selectedUsage?.reasoning_tokens)}</dd>
      </div>
      <div>
        <dt>{t("aiPanel.usage.cacheHit")}</dt>
        <dd>{formatTokenCount(selectedUsage?.prompt_cache_hit_tokens)}</dd>
      </div>
      <div>
        <dt>{t("aiPanel.usage.cacheMiss")}</dt>
        <dd>{formatTokenCount(selectedUsage?.prompt_cache_miss_tokens)}</dd>
      </div>
      <div>
        <dt>{t("aiPanel.usage.cost")}</dt>
        <dd>{formatCostAmount(selectedUsage)}</dd>
      </div>
    </dl>
  );
}
