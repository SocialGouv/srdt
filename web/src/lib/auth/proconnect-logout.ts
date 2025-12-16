/**
 * ProConnect logout utilities
 * Handles proper logout from both NextAuth and ProConnect (OpenID Connect provider)
 */

/**
 * Get the ProConnect end_session_endpoint URL based on environment
 */
export function getProConnectLogoutUrl(): string {
  const PROCONNECT_DOMAIN =
    process.env.NEXT_PUBLIC_PROCONNECT_ENV === "integration"
      ? "https://fca.integ01.dev-agentconnect.fr/api/v2"
      : "https://auth.agentconnect.gouv.fr/api/v2";

  // OpenID Connect standard logout endpoint
  return `${PROCONNECT_DOMAIN}/session/end`;
}

/**
 * Build the complete logout URL for ProConnect with required parameters
 * @param idToken - The ID token from the current session (optional - per OIDC spec)
 * @param postLogoutRedirectUri - Where to redirect after logout (must be registered in ProConnect)
 */
export function buildProConnectLogoutUrl(
  idToken: string,
  postLogoutRedirectUri: string
): string {
  const logoutUrl = getProConnectLogoutUrl();
  const params = new URLSearchParams({
    post_logout_redirect_uri: postLogoutRedirectUri,
  });

  // Only add id_token_hint if we have one (it's optional per OIDC spec)
  if (idToken) {
    params.set("id_token_hint", idToken);
  }

  return `${logoutUrl}?${params.toString()}`;
}
