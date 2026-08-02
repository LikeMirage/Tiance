import type { HoverSidebarSectionId } from "./sidebarSections";
import type { NestedMenuItem } from "../../../shared/model/nested-menu/usePersistentNestedMenuSelection";
import type { TranslationKey } from "../../../shared/i18n";

export type HoverSidebarIconKey =
  | "overview"
  | "knowledge"
  | "experience"
  | "roles"
  | "models"
  | "themes"
  | "tools"
  | "settings";

export interface HoverSidebarPrimaryItem {
  id: HoverSidebarSectionId;
  labelKey: TranslationKey;
  iconKey: HoverSidebarIconKey;
}

export type HoverSidebarSubItemId = string;

export interface HoverSidebarSubItem extends NestedMenuItem<HoverSidebarSubItemId> {
  isDefault?: boolean;
  label: string;
  readonly?: boolean;
  sectionId?: HoverSidebarSectionId;
}

export const primarySidebarItems: readonly HoverSidebarPrimaryItem[] = [
  {
    id: "overview",
    labelKey: "sidebar.sections.overview",
    iconKey: "overview",
  },
  {
    id: "tools",
    labelKey: "sidebar.sections.tools",
    iconKey: "tools",
  },
  {
    id: "knowledge",
    labelKey: "sidebar.sections.knowledge",
    iconKey: "knowledge",
  },
  {
    id: "experience",
    labelKey: "sidebar.sections.experience",
    iconKey: "experience",
  },
  {
    id: "roles",
    labelKey: "sidebar.sections.roles",
    iconKey: "roles",
  },
  {
    id: "models",
    labelKey: "sidebar.sections.models",
    iconKey: "models",
  },
  {
    id: "themes",
    labelKey: "sidebar.sections.themes",
    iconKey: "themes",
  },
  {
    id: "settings",
    labelKey: "sidebar.sections.settings",
    iconKey: "settings",
  },
];
