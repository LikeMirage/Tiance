import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { WarningCircle } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import { Tooltip } from "../../../shared/ui/tooltip";
import {
  formatCostAmount,
  formatTokenCount,
  type UsageDisplaySummary,
} from "../model/usageSummary";
import type { ChatComposerUsageState } from "./ChatComposerTypes";

const usagePopoverWidth = 310;
const usagePopoverGap = 8;

export function ChatUsagePopover({ usage }: { usage: ChatComposerUsageState }) {
  return (
    <div className="ai-panel__usage-area" ref={usage.areaRef}>
      <button
        className="ai-panel__usage-trigger"
        type="button"
        onClick={() => usage.onToggleOpen((current) => !current)}
      >
        {usage.contextTokens === null
          ? "--"
          : formatTokenCount(usage.contextTokens)}
      </button>
      {usage.isOpen ? <UsagePopoverPortal usage={usage} /> : null}
    </div>
  );
}

function UsagePopoverPortal({ usage }: { usage: ChatComposerUsageState }) {
  const { t } = useI18n();
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!usage.isOpen) return undefined;

    const updatePosition = () => {
      const anchor = usage.areaRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const popoverHeight = popoverRef.current?.offsetHeight ?? 210;
      const left = Math.min(
        window.innerWidth - usagePopoverWidth - usagePopoverGap,
        Math.max(usagePopoverGap, rect.right + usagePopoverGap - usagePopoverWidth),
      );
      const top = Math.max(usagePopoverGap, rect.top - popoverHeight - usagePopoverGap);
      setPosition({ left, top });
    };

    updatePosition();
    const frame = window.requestAnimationFrame(updatePosition);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [usage.areaRef, usage.isOpen, usage.scopeOptions.length, usage.scopeKey]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={popoverRef}
      className="ai-panel__usage-popover"
      role="dialog"
      aria-label={t("aiPanel.usage.aria")}
      onMouseDown={(event) => event.stopPropagation()}
      style={{
        left: position ? `${position.left}px` : "0",
        top: position ? `${position.top}px` : "0",
        visibility: position ? "visible" : "hidden",
      }}
    >
      <div className="ai-panel__usage-popover-head">
        <div className="ai-panel__usage-popover-title">
          <span>{t("aiPanel.usage.title")}</span>
          {(usage.selected?.estimated_record_count ?? 0) > 0 ? (
            <UsageEstimateWarning
              label={t("aiPanel.usage.totalEstimated")}
            />
          ) : null}
        </div>
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
      </div>
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
    </div>,
    document.body,
  );
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
