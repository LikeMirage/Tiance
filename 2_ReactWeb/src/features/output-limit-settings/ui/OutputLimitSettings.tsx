import { useEffect, useState } from "react";
import {
  DEFAULT_OUTPUT_LIMIT_MESSAGE,
  type OutputLimitAction,
  type OutputLimitPolicy,
} from "../../../entities/llm-chat/model/outputLimitPolicy";
import { useI18n } from "../../../shared/i18n";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import "./output-limit-settings.css";

export function OutputLimitSettings({ value, fallbackRecoveryCount, onChange }: {
  value: OutputLimitPolicy;
  fallbackRecoveryCount: number;
  onChange: (patch: Partial<OutputLimitPolicy>) => void;
}) {
  const { t } = useI18n();
  const [message, setMessage] = useState(value.output_limit_message);
  const [maximum, setMaximum] = useState(value.output_limit_max_recoveries?.toString() ?? "");
  useEffect(() => setMessage(value.output_limit_message), [value.output_limit_message]);
  useEffect(() => setMaximum(value.output_limit_max_recoveries?.toString() ?? ""), [value.output_limit_max_recoveries]);
  const label = (key: "outputLimitAction" | "outputLimitStop" | "outputLimitRetry" | "outputLimitSend"
    | "outputLimitSavePartial" | "outputLimitMaxRecoveries" | "outputLimitInheritedCount"
    | "outputLimitRetrySavedHint" | "outputLimitMessage" | "outputLimitResetMessage") => t(`aiPanel.basicSettings.${key}`);
  const commitMaximum = () => {
    const parsed = maximum.trim() ? Number(maximum) : null;
    if (parsed !== null && (!Number.isInteger(parsed) || parsed < 0)) {
      setMaximum(value.output_limit_max_recoveries?.toString() ?? "");
      return;
    }
    if (parsed !== value.output_limit_max_recoveries) onChange({ output_limit_max_recoveries: parsed });
  };
  return (
    <div className="output-limit-settings">
      <div className="output-limit-settings__row">
        <span>{label("outputLimitAction")}</span>
        <OptionSelect<OutputLimitAction>
          ariaLabel={label("outputLimitAction")}
          floating
          options={[
            { value: "stop", label: label("outputLimitStop") },
            { value: "retry", label: label("outputLimitRetry") },
            { value: "send_message", label: label("outputLimitSend") },
          ]}
          value={value.output_limit_action}
          onChange={(action) => onChange({
            output_limit_action: action,
            ...(action === "send_message" ? { output_limit_save_partial: true } : {}),
          })}
        />
      </div>
      <label className="output-limit-settings__row">
        <span>{label("outputLimitSavePartial")}</span>
        <input type="checkbox" checked={value.output_limit_save_partial}
          onChange={(event) => onChange({ output_limit_save_partial: event.target.checked })} />
      </label>
      {value.output_limit_action !== "stop" ? (
        <label className="output-limit-settings__row">
          <span>{label("outputLimitMaxRecoveries")}</span>
          <input aria-label={label("outputLimitMaxRecoveries")} type="number" min={0} step={1}
            placeholder={String(fallbackRecoveryCount)} value={maximum}
            title={label("outputLimitInheritedCount")}
            onChange={(event) => setMaximum(event.target.value)} onBlur={commitMaximum} />
        </label>
      ) : null}
      {value.output_limit_action === "retry" && value.output_limit_save_partial
        ? <small>{label("outputLimitRetrySavedHint")}</small> : null}
      {value.output_limit_action === "send_message" ? (
        <div className="output-limit-settings__message">
          <span>{label("outputLimitMessage")}</span>
          <textarea aria-label={label("outputLimitMessage")} value={message} rows={4} onChange={(event) => setMessage(event.target.value)}
            onBlur={() => { if (message !== value.output_limit_message) onChange({ output_limit_message: message }); }} />
          <button type="button" onClick={() => {
            setMessage(DEFAULT_OUTPUT_LIMIT_MESSAGE);
            onChange({ output_limit_message: DEFAULT_OUTPUT_LIMIT_MESSAGE });
          }}>{label("outputLimitResetMessage")}</button>
        </div>
      ) : null}
    </div>
  );
}
