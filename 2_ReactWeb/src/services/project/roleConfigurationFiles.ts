import type {
  RoleConfiguration,
  RoleConfigurationSection,
  RoleConfigurationSectionValueMap,
} from "../../entities/role-configuration/model/roleConfiguration";
import {
  formatRoleConfigurationSection,
  parseRoleConfigurationSection,
  ROLE_CONFIGURATION_FILE_NAMES,
  ROLE_CONFIGURATION_SECTIONS,
} from "../../entities/role-configuration/model/roleConfiguration";
import { getProjectFileContent } from "./getProjectFileContent";
import { saveProjectFileContent } from "./saveProjectFileContent";

export type LoadedRoleConfiguration = {
  configuration: RoleConfiguration;
  mtimes: Record<RoleConfigurationSection, number>;
};

export async function loadRoleConfiguration(
  projectId: string,
): Promise<LoadedRoleConfiguration> {
  const entries = await Promise.all(
    ROLE_CONFIGURATION_SECTIONS.map(async (section) => {
      const response = await getProjectFileContent(
        projectId,
        ROLE_CONFIGURATION_FILE_NAMES[section],
      );
      return [
        section,
        parseRoleConfigurationSection(section, response.content),
        response.mtime_ms,
      ] as const;
    }),
  );

  const configuration = {} as RoleConfiguration;
  const mtimes = {} as Record<RoleConfigurationSection, number>;
  for (const [section, value, mtimeMs] of entries) {
    Object.assign(configuration, { [section]: value });
    mtimes[section] = mtimeMs;
  }
  return { configuration, mtimes };
}

export async function saveRoleConfigurationSection<
  Section extends RoleConfigurationSection,
>(
  projectId: string,
  section: Section,
  value: RoleConfigurationSectionValueMap[Section],
  expectedMtimeMs: number,
) {
  return saveProjectFileContent(
    projectId,
    ROLE_CONFIGURATION_FILE_NAMES[section],
    formatRoleConfigurationSection(value),
    { expectedMtimeMs },
  );
}
