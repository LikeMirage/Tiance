import type { FunctionalModelSettingsSectionId } from "../../../features/functional-model-settings/model/functionalModelSections";

export type WorkspaceSettingsSectionId =
  | "language"
  | "software-update"
  | "github"
  | "network"
  | "token-estimation"
  | FunctionalModelSettingsSectionId;

const functionalModelSectionIds: readonly FunctionalModelSettingsSectionId[] = [
  "default-conversation",
  "conversation-naming",
  "memory-compression",
];

export function isFunctionalModelSettingsSection(
  sectionId: WorkspaceSettingsSectionId,
): sectionId is FunctionalModelSettingsSectionId {
  return functionalModelSectionIds.includes(sectionId as FunctionalModelSettingsSectionId);
}
