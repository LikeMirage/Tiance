import { useEffect, useRef, useState } from "react";
import { Cards } from "@phosphor-icons/react";

import { useI18n } from "../../../shared/i18n";
import type { ProjectOverviewLayoutMode } from "../model/projectOverviewLayout";

type ProjectOverviewLayoutSwitcherProps = {
  onChange: (mode: ProjectOverviewLayoutMode) => void;
  value: ProjectOverviewLayoutMode;
};

export function ProjectOverviewLayoutSwitcher({
  onChange,
  value,
}: ProjectOverviewLayoutSwitcherProps) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && rootRef.current?.contains(target)) return;
      setIsOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };

    window.addEventListener("pointerdown", handlePointerDown, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const options: Array<{
    label: string;
    value: ProjectOverviewLayoutMode;
  }> = [
    {
      label: t("projectOverview.layout.grid"),
      value: "grid",
    },
    {
      label: t("projectOverview.layout.wide"),
      value: "wide",
    },
    {
      label: t("projectOverview.layout.roller"),
      value: "roller",
    },
    {
      label: t("projectOverview.layout.stack"),
      value: "stack",
    },
  ];
  const currentLabel = options.find((option) => option.value === value)?.label ?? "";
  const menuOptions = options.filter((option) => option.value !== value);

  return (
    <div
      className={[
        "project-category-overview__layout-switcher",
        isOpen ? "project-category-overview__layout-switcher--open" : "",
      ].filter(Boolean).join(" ")}
      ref={rootRef}
    >
      {isOpen ? (
        <div
          className="project-category-overview__layout-menu"
          role="menu"
          aria-label={t("projectOverview.layout.menuAria")}
        >
          {menuOptions.map((option) => (
            <button
              key={option.value}
              className="project-category-overview__layout-option"
              type="button"
              role="menuitemradio"
              aria-checked={false}
              onClick={() => {
                onChange(option.value);
                setIsOpen(false);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
      <button
        className="project-category-overview__layout-trigger"
        type="button"
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label={t("projectOverview.layout.openAria")}
        title={t("projectOverview.layout.openAria")}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className="project-category-overview__layout-trigger-icon" aria-hidden="true">
          <Cards size={16} weight="bold" />
        </span>
        <span className="project-category-overview__layout-trigger-label">{currentLabel}</span>
      </button>
    </div>
  );
}
