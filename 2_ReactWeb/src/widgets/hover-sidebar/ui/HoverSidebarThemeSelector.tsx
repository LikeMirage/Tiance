import { useEffect, useMemo, useRef, useState } from "react";
import { Check, MagnifyingGlass, Palette } from "@phosphor-icons/react";

import type {
  Project,
  ProjectCategory,
} from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import type { AppThemeControl } from "../../../shared/theme";

const ALL_THEME_CATEGORY_ID = "__all_themes__";

type ThemeOption = {
  categoryId: string | null;
  label: string;
  value: string;
};

type HoverSidebarThemeSelectorProps = {
  categories: ProjectCategory[];
  isSidebarExpanded: boolean;
  themeControl: AppThemeControl;
  themeProjects: Project[];
};

export function HoverSidebarThemeSelector({
  categories,
  isSidebarExpanded,
  themeControl,
  themeProjects,
}: HoverSidebarThemeSelectorProps) {
  const { t } = useI18n();
  const [isHovered, setIsHovered] = useState(false);
  const [isFocusWithin, setIsFocusWithin] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategoryId, setSelectedCategoryId] = useState(ALL_THEME_CATEGORY_ID);
  const hasUserSelectedCategoryRef = useRef(false);
  const wasOpenRef = useRef(false);
  const activeThemeId = themeControl.activeThemeId ?? "";
  const allThemeOptions = useMemo(
    () => buildThemeOptions(themeControl, themeProjects),
    [themeControl, themeProjects],
  );
  const activeThemeOption = allThemeOptions.find(
    (option) => option.value === activeThemeId,
  );
  const activeThemeLabel =
    activeThemeOption?.label ||
    themeControl.activeThemeName ||
    t("sidebar.theme.fallback");
  const isOpen = isSidebarExpanded && (isHovered || isFocusWithin);
  const normalizedSearchQuery = searchQuery.trim().toLocaleLowerCase();
  const effectiveCategoryId = normalizedSearchQuery
    ? ALL_THEME_CATEGORY_ID
    : selectedCategoryId;
  const visibleThemeOptions = allThemeOptions.filter((option) => {
    if (normalizedSearchQuery) {
      return option.label.toLocaleLowerCase().includes(normalizedSearchQuery);
    }
    return (
      effectiveCategoryId === ALL_THEME_CATEGORY_ID ||
      option.categoryId === effectiveCategoryId
    );
  });

  useEffect(() => {
    if (!isSidebarExpanded) {
      setIsHovered(false);
      setIsFocusWithin(false);
    }
  }, [isSidebarExpanded]);

  useEffect(() => {
    if (!isOpen) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) return;

    wasOpenRef.current = true;
    hasUserSelectedCategoryRef.current = false;
    setSearchQuery("");
    setSelectedCategoryId(
      activeThemeOption?.categoryId ?? ALL_THEME_CATEGORY_ID,
    );
    themeControl.onOpenThemeMenu();
  }, [
    activeThemeOption?.categoryId,
    isOpen,
    themeControl.onOpenThemeMenu,
  ]);

  useEffect(() => {
    if (
      !isOpen ||
      hasUserSelectedCategoryRef.current ||
      searchQuery ||
      !activeThemeOption?.categoryId
    ) {
      return;
    }
    setSelectedCategoryId(activeThemeOption.categoryId);
  }, [
    activeThemeOption?.categoryId,
    isOpen,
    searchQuery,
  ]);

  return (
    <div
      className={
        isOpen
          ? "hover-sidebar__theme-selector hover-sidebar__theme-selector--open"
          : "hover-sidebar__theme-selector"
      }
      onPointerEnter={() => {
        setIsHovered(true);
      }}
      onPointerLeave={() => {
        setIsHovered(false);
      }}
      onFocus={() => {
        setIsFocusWithin(true);
      }}
      onBlur={(event) => {
        if (
          event.relatedTarget instanceof Node &&
          event.currentTarget.contains(event.relatedTarget)
        ) {
          return;
        }
        setIsFocusWithin(false);
      }}
    >
      {isOpen ? (
        <div className="hover-sidebar__theme-panel">
          <label className="hover-sidebar__theme-search">
            <MagnifyingGlass
              className="hover-sidebar__theme-search-icon"
              weight="bold"
              aria-hidden="true"
            />
            <input
              className="hover-sidebar__theme-search-input"
              type="search"
              value={searchQuery}
              placeholder={t("sidebar.theme.search")}
              aria-label={t("sidebar.theme.search")}
              onChange={(event) => {
                setSearchQuery(event.target.value);
              }}
            />
          </label>

          <div className="hover-sidebar__theme-browser">
            <div
              className="hover-sidebar__theme-categories"
              role="navigation"
              aria-label={t("sidebar.theme.categories")}
            >
              <ThemeCategoryButton
                count={allThemeOptions.length}
                isSelected={effectiveCategoryId === ALL_THEME_CATEGORY_ID}
                label={t("sidebar.theme.all")}
                onSelect={() => {
                  hasUserSelectedCategoryRef.current = true;
                  setSearchQuery("");
                  setSelectedCategoryId(ALL_THEME_CATEGORY_ID);
                }}
              />
              {categories.map((category) => (
                <ThemeCategoryButton
                  key={category.category_id}
                  count={allThemeOptions.filter(
                    (option) => option.categoryId === category.category_id,
                  ).length}
                  isSelected={effectiveCategoryId === category.category_id}
                  label={category.name}
                  onSelect={() => {
                    hasUserSelectedCategoryRef.current = true;
                    setSearchQuery("");
                    setSelectedCategoryId(category.category_id);
                  }}
                />
              ))}
            </div>

            <div
              className="hover-sidebar__theme-menu"
              role="listbox"
              aria-label={t("sidebar.theme.select")}
            >
              {visibleThemeOptions.length > 0 ? (
                visibleThemeOptions.map((option) => {
                  const isActive = option.value === activeThemeId;
                  return (
                    <button
                      key={option.value}
                      className={
                        isActive
                          ? "hover-sidebar__theme-option hover-sidebar__theme-option--active"
                          : "hover-sidebar__theme-option"
                      }
                      type="button"
                      role="option"
                      aria-selected={isActive}
                      disabled={themeControl.isLoading}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        themeControl.onSelectTheme(option.value);
                      }}
                    >
                      <span className="hover-sidebar__theme-option-label">
                        {option.label}
                      </span>
                      {isActive ? (
                        <Check
                          className="hover-sidebar__theme-option-check"
                          weight="bold"
                          aria-hidden="true"
                        />
                      ) : null}
                    </button>
                  );
                })
              ) : (
                <div className="hover-sidebar__theme-empty">
                  {t("sidebar.theme.empty")}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      <ThemeSelectorTrigger
        activeThemeLabel={activeThemeLabel}
        disabled={themeControl.isLoading}
        isOpen={isOpen}
      />
    </div>
  );
}

function ThemeCategoryButton({
  count,
  isSelected,
  label,
  onSelect,
}: {
  count: number;
  isSelected: boolean;
  label: string;
  onSelect: () => void;
}) {
  return (
    <button
      className={
        isSelected
          ? "hover-sidebar__theme-category hover-sidebar__theme-category--active"
          : "hover-sidebar__theme-category"
      }
      type="button"
      aria-pressed={isSelected}
      onClick={onSelect}
    >
      <span className="hover-sidebar__theme-category-label">{label}</span>
      <span className="hover-sidebar__theme-category-count">{count}</span>
    </button>
  );
}

function ThemeSelectorTrigger({
  activeThemeLabel,
  disabled,
  isOpen,
}: {
  activeThemeLabel: string;
  disabled: boolean;
  isOpen: boolean;
}) {
  const { t } = useI18n();
  return (
    <button
      className="hover-sidebar__theme-trigger"
      type="button"
      aria-label={t("sidebar.theme.select")}
      disabled={disabled}
      aria-expanded={isOpen}
    >
      <span className="hover-sidebar__theme-icon" aria-hidden="true">
        <Palette className="hover-sidebar__theme-glyph" weight="bold" />
      </span>
      <span className="hover-sidebar__theme-label">{activeThemeLabel}</span>
    </button>
  );
}

function buildThemeOptions(
  themeControl: AppThemeControl,
  themeProjects: Project[],
): ThemeOption[] {
  const categoryByThemeId = new Map(
    themeProjects.map((project) => [
      getThemeIdFromRootPath(project.root_path),
      project.category_id,
    ]),
  );
  const summaries = [...themeControl.themes];

  if (
    themeControl.activeThemeId &&
    !summaries.some((theme) => theme.id === themeControl.activeThemeId)
  ) {
    summaries.unshift({
      id: themeControl.activeThemeId,
      mode: themeControl.mode,
      name: themeControl.activeThemeName,
    });
  }

  return summaries.map((theme) => ({
    categoryId: categoryByThemeId.get(theme.id) ?? null,
    label: theme.name,
    value: theme.id,
  }));
}

function getThemeIdFromRootPath(rootPath: string): string {
  return rootPath
    .replaceAll("\\", "/")
    .split("/")
    .filter(Boolean)
    .pop() ?? "";
}
