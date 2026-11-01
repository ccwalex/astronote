/**
 * Cache-hydrated pages look complete but are not save-authoritative until GET /api/projects/:id.
 */
export function shouldSkipProjectHydrateFetch(
  isHydrated: boolean,
  hasAuthoritativeSnapshot: boolean
): boolean {
  return isHydrated && hasAuthoritativeSnapshot;
}
