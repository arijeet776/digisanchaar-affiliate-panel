/**
 * Public registration link for an invite. The URL carries ONLY the opaque,
 * single-use invite token - never a Manager ID. Which Manager (if any) the
 * invite belongs to is resolved server-side from the token.
 */
export function buildInviteLink(token: string): string {
  return `${window.location.origin}/register/${encodeURIComponent(token)}`;
}
