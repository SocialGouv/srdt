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
        console.log("🔍 Fetching and decoding userinfo JWT from ProConnect");

        const response = await fetch(`${PROCONNECT_DOMAIN}/userinfo`, {
          headers: {
            Authorization: `Bearer ${tokens.access_token}`,
          },
        });

        if (!response.ok) {
          console.error("❌ Userinfo request failed:", response.status);
          throw new Error(`Userinfo request failed: ${response.status}`);
        }

        // ProConnect returns a JWT signed with HS256
        const jwt = await response.text();
        console.log(
          "  Received JWT (first 50 chars):",
          jwt.substring(0, 50) + "..."
        );

        try {
          // Decode the JWT header to check the algorithm
          const header = jose.decodeProtectedHeader(jwt);
          console.log("  JWT algorithm:", header.alg);

          if (header.alg === "HS256") {
            // For HS256, use the client_secret
            console.log("  Using HS256 verification with client_secret");
            const secret = new TextEncoder().encode(options.clientSecret);
            const { payload } = await jose.jwtVerify(jwt, secret, {
              algorithms: ["HS256"],
            });
            console.log("✅ Userinfo decoded successfully:", payload);
            return payload as unknown as P;
          } else if (header.alg === "RS256" || header.alg === "ES256") {
            // For RS256/ES256, try different JWKS URLs
            console.log(`  Using ${header.alg} verification with JWKS`);

            const jwksUrls = [
              `${PROCONNECT_DOMAIN}/jwks`,
              `${PROCONNECT_DOMAIN}/.well-known/jwks.json`,
            ];

            for (const jwksUrl of jwksUrls) {
              try {
                console.log(`    Trying JWKS URL: ${jwksUrl}`);
                const JWKS = jose.createRemoteJWKSet(new URL(jwksUrl));
                const { payload } = await jose.jwtVerify(jwt, JWKS, {
                  algorithms: ["RS256", "ES256"],
                });
                console.log(`    ✓ Verified with ${jwksUrl}`);
                console.log("✅ Userinfo decoded successfully:", payload);
                return payload as unknown as P;
              } catch (err) {
                console.log(`    ✗ Failed:`, (err as Error).message);
              }
            }

            throw new Error("Could not verify JWT with any JWKS URL");
          } else {
            throw new Error(`Unsupported algorithm: ${header.alg}`);
          }
        } catch (error) {
          console.error("❌ Failed to decode userinfo JWT:", error);
          console.error(
            "  Tip: Change to HS256 in ProConnect for simpler setup"
          );
          throw error;
        }
      },
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
