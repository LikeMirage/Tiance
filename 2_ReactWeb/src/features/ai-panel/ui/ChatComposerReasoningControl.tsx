import { Check } from "@phosphor-icons/react";
import { useId } from "react";
import { EmbeddedPanel } from "@/shared/ui/embedded-panel/EmbeddedPanel";
import { useI18n } from "../../../shared/i18n";
import type { ChatComposerReasoningState } from "./ChatComposerTypes";

export function ChatComposerReasoningControl({
  reasoning, isOpen, onOpenChange, panelContainer,
}: {
  reasoning: ChatComposerReasoningState;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  panelContainer: HTMLElement | null;
}) {
  const { t } = useI18n();
  const panelId = useId();
  const label = t("aiPanel.basicSettings.reasoningDepth");
  const activeLabel = reasoning.options.find(option => option.value === reasoning.activeMode)?.label ?? reasoning.activeMode;
  if (!reasoning.isVisible) return null;

  return <>
    <button type="button" className="ai-panel__reasoning-trigger"
      aria-label={label} title={`${label} · ${activeLabel}`}
      aria-haspopup="dialog" aria-expanded={isOpen} aria-controls={isOpen ? panelId : undefined}
      onClick={() => onOpenChange(!isOpen)}>
      {activeLabel}
    </button>
    {isOpen ? <EmbeddedPanel container={panelContainer} id={panelId}
      title={label} ariaLabel={label} onClose={() => onOpenChange(false)}>
      <div className="ai-panel__reasoning-options" role="group" aria-label={label}>
        {reasoning.options.map(option => <button key={option.value} type="button"
          className="ai-panel__reasoning-option" aria-pressed={option.value === reasoning.activeMode}
          onClick={() => {
            if (option.value !== reasoning.activeMode) reasoning.onChange(option.value);
            onOpenChange(false);
          }}>
          <span>{option.label}</span>
          {option.value === reasoning.activeMode ? <Check size={16} aria-hidden="true" /> : null}
        </button>)}
      </div>
    </EmbeddedPanel> : null}
  </>;
}
