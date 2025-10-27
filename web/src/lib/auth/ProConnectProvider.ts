import type { OAuthConfig, OAuthUserConfig } from "next-auth/providers/oauth";

export interface ProConnectProfile {
  sub: string;
  email: string;
  email_verified?: boolean;
  given_name?: string;
  usual_name?: string;
  family_name?: string;
  preferred_username?: string;
  siret?: string;
  organizational_unit?: string;
  belonging_population?: string;
  phone_number?: string;
  job?: string;
}

export default function ProConnectProvider<P extends ProConnectProfile>(
  options: OAuthUserConfig<P>
): OAuthConfig<P> {
  // ProConnect/AgentConnect domains:
  // This provider supports Internet environments (default)
  // - Internet Integration: fca.integ01.dev-agentconnect.fr
  // - Internet Production: auth.agentconnect.gouv.fr
  // For RIE environments, set PROCONNECT_DOMAIN env var manually:
  // - RIE Integration: fca.integ02.agentconnect.rie.gouv.fr
  // - RIE Production: auth.agentconnect.rie.gouv.fr

  const PROCONNECT_DOMAIN =
    process.env.PROCONNECT_ENV === "production"
      ? "https://auth.agentconnect.gouv.fr/api/v2/"
      : "https://fca.integ01.dev-agentconnect.fr/api/v2";

  console.log("🔗 ProConnect Provider Configuration:");
  console.log("  Domain:", PROCONNECT_DOMAIN);
  console.log(
    "  WellKnown:",
    `${PROCONNECT_DOMAIN}/.well-known/openid-configuration`
  );
  console.log("  Client ID:", options.clientId ? "✓ Set" : "✗ Missing");
  console.log("  Client Secret:", options.clientSecret ? "✓ Set" : "✗ Missing");

  return {
    id: "proconnect",
    name: "ProConnect",
    type: "oauth",
    wellKnown: `${PROCONNECT_DOMAIN}/.well-known/openid-configuration`,
    authorization: {
      params: {
        scope: "openid email profile",
        acr_values: "eidas1", // Level of authentication required
      },
    },
    idToken: true,
    checks: ["pkce", "state"],
    client: {
      token_endpoint_auth_method: "client_secret_post",
    },
    profile(profile) {
      console.log("👤 Profile mapping:", profile);
      return {
        id: profile.sub,
        email: profile.email,
        name: profile.given_name
          ? `${profile.given_name} ${
              profile.usual_name || profile.family_name || ""
            }`
          : profile.preferred_username || profile.email,
        image: null,
        given_name: profile.given_name,
        family_name: profile.family_name || profile.usual_name,
        siret: profile.siret,
        organizational_unit: profile.organizational_unit,
        belonging_population: profile.belonging_population,
        phone_number: profile.phone_number,
        job: profile.job,
      };
    },
    style: {
      logo: "/proconnect-logo.svg",
      logoDark: "/proconnect-logo.svg",
      bg: "#fff",
      text: "#000091",
      bgDark: "#000091",
      textDark: "#fff",
    },
    options,
  };
}
