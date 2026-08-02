import type { ReactNode } from "react";

import "./collection-view-tabs.css";

export type CollectionViewTab<ViewId extends string> = {
  disabled?: boolean;
  icon?: ReactNode;
  id: ViewId;
  label: string;
};

type CollectionViewTabsProps<ViewId extends string> = {
  activeView: ViewId;
  ariaLabel: string;
  onChange: (view: ViewId) => void;
  tabs: readonly CollectionViewTab<ViewId>[];
};

export function CollectionViewTabs<ViewId extends string>({
  activeView,
  ariaLabel,
  onChange,
  tabs,
}: CollectionViewTabsProps<ViewId>) {
  return (
    <div className="collection-view-tabs" role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab) => {
        const isActive = tab.id === activeView;
        return (
          <button
            className={[
              "collection-view-tabs__tab",
              isActive ? "collection-view-tabs__tab--active" : "",
            ].filter(Boolean).join(" ")}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={tab.disabled}
            key={tab.id}
            onClick={() => {
              if (!isActive) onChange(tab.id);
            }}
          >
            {tab.icon ? (
              <span className="collection-view-tabs__icon" aria-hidden="true">
                {tab.icon}
              </span>
            ) : null}
            <span>{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}
