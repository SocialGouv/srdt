import type { OAuthConfig, OAuthUserConfig } from "next-auth/providers/oauth";
import * as jose from "jose";

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
      ? "https://auth.agentconnect.gouv.fr/api/v2"
      : "https://fca.integ01.dev-agentconnect.fr/api/v2";

  // When CHARON_URL is set (dev branches), route OAuth discovery through Charon proxy
  // to allow dynamic branch URLs without registering each one in ProConnect.
  // Charon rewrites authorization/token endpoints but keeps userinfo/jwks direct.
  const wellKnownUrl = process.env.CHARON_URL
    ? `${process.env.CHARON_URL}/proconnect/.well-known/openid-configuration`
    : `${PROCONNECT_DOMAIN}/.well-known/openid-configuration`;

  return {
    id: "proconnect",
    name: "ProConnect",
    type: "oauth",
    wellKnown: wellKnownUrl,
    authorization: {
      params: {
        // ProConnect requires individual scopes for each claim
        // See: https://partenaires.proconnect.gouv.fr/docs/fournisseur-service/scope-claims
        scope: "openid email given_name usual_name uid siret",
        acr_values: "eidas1", // Level of authentication required
      },
    },
    idToken: true,
    checks: ["pkce", "state"],
    client: {
      token_endpoint_auth_method: "client_secret_post",
    },
    // ProConnect returns userinfo as a JWT signed with HS256 (using client_secret)
    // We need to manually fetch and verify it
    // See: https://partenaires.proconnect.gouv.fr/docs/fournisseur-service/scope-claims
    userinfo: {
      url: `${PROCONNECT_DOMAIN}/userinfo`,
      async request({ tokens }) {
        const response = await fetch(`${PROCONNECT_DOMAIN}/userinfo`, {
          headers: {
            Authorization: `Bearer ${tokens.access_token}`,
          },
        });

        if (!response.ok) {
          throw new Error(`Userinfo request failed: ${response.status}`);
        }

        // ProConnect returns userinfo as a signed JWT (HS256, RS256, or ES256)
        const jwt = await response.text();
        const header = jose.decodeProtectedHeader(jwt);

        if (header.alg === "HS256") {
          // For HS256, verify with client_secret
          const secret = new TextEncoder().encode(options.clientSecret);
          const { payload } = await jose.jwtVerify(jwt, secret, {
            algorithms: ["HS256"],
          });
          return payload as unknown as P;
        } else if (header.alg === "RS256" || header.alg === "ES256") {
          // For RS256/ES256, verify with JWKS
          const jwksUrls = [
            `${PROCONNECT_DOMAIN}/jwks`,
            `${PROCONNECT_DOMAIN}/.well-known/jwks.json`,
          ];

          for (const jwksUrl of jwksUrls) {
            try {
              const JWKS = jose.createRemoteJWKSet(new URL(jwksUrl));
              const { payload } = await jose.jwtVerify(jwt, JWKS, {
                algorithms: ["RS256", "ES256"],
              });
              return payload as unknown as P;
            } catch {
              // Try next URL
              continue;
            }
          }

          throw new Error(
            `Could not verify ${header.alg} JWT with available JWKS endpoints`
          );
        }

        throw new Error(`Unsupported JWT algorithm: ${header.alg}`);
      },
    },
    profile(profile) {
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
