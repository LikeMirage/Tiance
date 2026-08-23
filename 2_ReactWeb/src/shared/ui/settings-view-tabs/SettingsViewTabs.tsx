import type { ReactNode } from "react";

import "./settings-view-tabs.css";

export type SettingsViewTab<ViewId extends string> = {
  disabled?: boolean;
  id: ViewId;
  label: ReactNode;
};

type SettingsViewTabsProps<ViewId extends string> = {
  activeView: ViewId;
  ariaLabel: string;
  compact?: boolean;
  disabled?: boolean;
  onChange: (view: ViewId) => void;
  tabs: readonly SettingsViewTab<ViewId>[];
};

export function SettingsViewTabs<ViewId extends string>({
  activeView,
  ariaLabel,
  compact = false,
  disabled = false,
  onChange,
  tabs,
}: SettingsViewTabsProps<ViewId>) {
  return (
    <div
      className={compact
        ? "settings-view-tabs settings-view-tabs--compact"
        : "settings-view-tabs"}
      role="tablist"
      aria-label={ariaLabel}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeView;
        return (
          <button
            className={isActive
              ? "settings-view-tabs__tab settings-view-tabs__tab--active"
              : "settings-view-tabs__tab"}
            disabled={disabled || tab.disabled}
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => {
              if (!isActive) onChange(tab.id);
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
