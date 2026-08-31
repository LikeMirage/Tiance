import type { FunctionalModelSettingsSectionId } from "../../../features/functional-model-settings/model/functionalModelSections";

export type WorkspaceSettingsSectionId =
  | "language"
  | "software-update"
  | "announcements"
  | "github"
  | "global-memory"
  | "network"
  | "access-management"
  | "access-security"
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
