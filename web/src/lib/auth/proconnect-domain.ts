/**
 * ProConnect/AgentConnect domains:
 * This app uses Internet environments
 * - Internet Integration: fca.integ01.dev-agentconnect.fr
 * - Internet Production: auth.agentconnect.gouv.fr
 * For RIE environments, set PROCONNECT_DOMAIN env var manually:
 * - RIE Integration: fca.integ02.agentconnect.rie.gouv.fr
 * - RIE Production: auth.agentconnect.rie.gouv.fr
 *
 * Server-only: PROCONNECT_ENV is read at runtime from the pod env, so login
 * and logout always target the same ProConnect environment.
 */
export function getProConnectDomain(): string {
  return process.env.PROCONNECT_ENV === "production"
    ? "https://auth.agentconnect.gouv.fr/api/v2"
    : "https://fca.integ01.dev-agentconnect.fr/api/v2";
}
