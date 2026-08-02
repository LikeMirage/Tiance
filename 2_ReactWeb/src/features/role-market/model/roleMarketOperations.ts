import type { ProjectCategory } from "../../../entities/project/model/project";
import type { RoleMarketInstallationStatus, RoleMarketRole } from "./roleMarket";

export type RoleMarketOperationPhase = "idle" | "installing" | "success" | "error";

export function isRoleMarketActionDisabled(
  installationStatus: RoleMarketInstallationStatus,
  operationPhase?: RoleMarketOperationPhase,
) {
  return operationPhase === "installing" || installationStatus === "installed";
}

export type InstalledRoleResult = {
  projectId: string;
  roleId: string;
  version: string;
};

export function applyInstalledRoleResult(
  roles: readonly RoleMarketRole[],
  result: InstalledRoleResult,
) {
  return roles.map((role) => role.id === result.roleId ? {
    ...role,
    installationStatus: "installed" as const,
    localProjectId: result.projectId,
    localVersion: result.version,
  } : role);
}

export function filterRoleCategories(categories: readonly ProjectCategory[]) {
  return categories.filter((category) => category.category_kind === "role");
}

export class LatestRoleMarketRequest {
  private currentId = 0;

  begin() {
    this.currentId += 1;
    return this.currentId;
  }

  isCurrent(requestId: number) {
    return this.currentId === requestId;
  }
}
