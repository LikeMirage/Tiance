import type {
  RoleMarketFilters,
  RoleMarketRole,
} from "./roleMarket";

export function filterRoleMarketRoles(
  roles: readonly RoleMarketRole[],
  filters: RoleMarketFilters,
  query: string,
) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return roles.filter((role) => {
    if (filters.authors.length && !filters.authors.includes(role.author)) return false;
    if (filters.statuses.length && !filters.statuses.includes(role.installationStatus)) {
      return false;
    }
    if (!normalizedQuery) return true;
    return [role.name, role.id, role.author, role.summary]
      .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function listRoleMarketAuthors(roles: readonly RoleMarketRole[]) {
  return [...new Set(roles.map((role) => role.author))].sort((left, right) => (
    left.localeCompare(right)
  ));
}
