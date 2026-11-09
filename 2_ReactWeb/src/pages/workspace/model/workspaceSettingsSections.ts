import type { FunctionalModelSettingsSectionId } from "../../../features/functional-model-settings/model/functionalModelSections";

export type WorkspaceSettingsSectionId =
  | "default-roles"
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
  "conversation-naming",
  "memory-compression",
  "project-memory-management",
  "global-memory-management",
];

export function isFunctionalModelSettingsSection(
  sectionId: WorkspaceSettingsSectionId,
): sectionId is FunctionalModelSettingsSectionId {
  return functionalModelSectionIds.includes(sectionId as FunctionalModelSettingsSectionId);
}
