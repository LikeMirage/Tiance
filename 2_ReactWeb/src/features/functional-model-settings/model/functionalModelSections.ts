import type {
  NestedMenuItem,
  PersistentNestedMenuConfig,
} from "../../../shared/model/nested-menu/usePersistentNestedMenuSelection";
import type { TranslationKey } from "../../../shared/i18n";

export type FunctionalModelSettingsSectionId =
  | "default-conversation"
  | "conversation-naming"
  | "memory-compression"
  | "project-memory-management"
  | "global-memory-management";

export type FunctionalModelSettingsSectionItem =
  NestedMenuItem<FunctionalModelSettingsSectionId> & {
    labelKey: TranslationKey;
  };

export const functionalModelSettingsSections: readonly FunctionalModelSettingsSectionItem[] = [
  {
    id: "default-conversation",
    label: "默认会话角色",
    labelKey: "functionalModelSettings.sections.defaultConversation",
  },
  {
    id: "conversation-naming",
    label: "会话命名模型",
    labelKey: "functionalModelSettings.sections.conversationNaming",
  },
  {
    id: "memory-compression",
    label: "记忆压缩模型",
    labelKey: "functionalModelSettings.sections.memoryCompression",
  },
  {
    id: "project-memory-management",
    label: "项目记忆管理模型",
    labelKey: "functionalModelSettings.sections.projectMemoryManagement",
  },
  {
    id: "global-memory-management",
    label: "全局记忆管理模型",
    labelKey: "functionalModelSettings.sections.globalMemoryManagement",
  },
];

export const functionalModelSettingsNestedMenuConfig = {
  defaultItemId: "default-conversation",
  items: functionalModelSettingsSections,
  storageKey: "tiance.settings.functional-model-section",
} satisfies PersistentNestedMenuConfig<FunctionalModelSettingsSectionItem>;
