import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import { useI18n } from "../../../shared/i18n";
import type { ChatComposerReasoningState } from "./ChatComposerTypes";

export function ChatComposerReasoningControl({
  reasoning,
}: {
  reasoning: ChatComposerReasoningState;
}) {
  const { t } = useI18n();
  return reasoning.isVisible ? (
    <OptionSelect
      ariaLabel={t("aiPanel.basicSettings.reasoningDepth")}
      className="ai-panel__reasoning-select"
      floating
      options={reasoning.options}
      value={reasoning.activeMode}
      onChange={reasoning.onChange}
    />
  ) : null;
}
