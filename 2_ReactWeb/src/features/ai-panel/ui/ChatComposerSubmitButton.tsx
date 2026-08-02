import { CaretUp, Stop } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import type {
  ChatComposerGenerationState,
  ChatComposerInputState,
} from "./ChatComposerTypes";

export function ComposerSubmitButton({
  generation,
  input,
}: {
  generation: ChatComposerGenerationState;
  input: ChatComposerInputState;
}) {
  const { t } = useI18n();
  const actionLabel = generation.isStreaming
    ? t("aiPanel.composer.stopGeneration")
    : t("aiPanel.composer.send");
  return (
    <button
      className={
        generation.isStreaming
          ? "ai-panel__send ai-panel__send--stop"
          : "ai-panel__send"
      }
      type="button"
      aria-label={actionLabel}
      title={generation.isStreaming ? actionLabel : undefined}
      disabled={!generation.isStreaming && !input.canSend}
      onClick={() => {
        if (generation.isStreaming) {
          generation.onStop();
          return;
        }
        input.onSend();
      }}
    >
      {generation.isStreaming ? (
        <Stop size={18} weight="fill" />
      ) : (
        <CaretUp size={20} weight="bold" />
      )}
    </button>
  );
}
