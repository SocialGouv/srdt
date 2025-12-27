import { NextAuthOptions } from "next-auth";
import ProConnectProvider, { ProConnectProfile } from "./ProConnectProvider";
import * as Sentry from "@sentry/nextjs";

// Allowed email domains for access control
const ALLOWED_EMAIL_DOMAINS = [
  "aisne.gouv.fr",
  "bouches-du-rhone.gouv.fr",
  "calvados.gouv.fr",
  "charente-maritime.gouv.fr",
  "charente.gouv.fr",
  "correze.gouv.fr",
  "creuse.gouv.fr",
  "deux-sevres.gouv.fr",
  "dordogne.gouv.fr",
  "drieets.gouv.fr",
  "eure.gouv.fr",
  "fabrique.social.gouv.fr",
  "gironde.gouv.fr",
  "haute-vienne.gouv.fr",
  "landes.gouv.fr",
  "lot-et-garonne.gouv.fr",
  "maine-et-loire.gouv.fr",
  "manche.gouv.fr",
  "nord.gouv.fr",
  "oise.gouv.fr",
  "orne.gouv.fr",
  "pas-de-calais.gouv.fr",
  "pyrenees-atlantiques.gouv.fr",
  "seine-maritime.gouv.fr",
  "sg.social.gouv.fr",
  "somme.gouv.fr",
  "travail.gouv.fr",
  "vienne.gouv.fr",
  // Add beta.gouv.fr for local development
  ...(process.env.NODE_ENV === "development" ? ["beta.gouv.fr"] : []),
];

// Helper function to check if email domain is allowed
function isEmailDomainAllowed(email: string | null | undefined): boolean {
  if (!email) return false;

  const emailDomain = email.split("@")[1]?.toLowerCase();
  if (!emailDomain) return false;

  return ALLOWED_EMAIL_DOMAINS.some(
    (domain) => emailDomain === domain.toLowerCase()
  );
}

// Helper function to check if email is in beta testers list
function isBetaTesterEmail(email: string | null | undefined): boolean {
  if (!email) return false;

  const betaTestersListEnv = process.env.BETA_TESTERS_LIST;
  if (!betaTestersListEnv) return false;

  const betaTestersList = betaTestersListEnv
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);

  return betaTestersList.includes(email.toLowerCase());
}

export const authOptions: NextAuthOptions = {
  providers: [
    ProConnectProvider({
      clientId: process.env.PROCONNECT_CLIENT_ID!,
      clientSecret: process.env.PROCONNECT_CLIENT_SECRET!,
    }),
  ],
  callbacks: {
    async signIn() {
      // Always return true to allow session creation with id_token
      // This is needed for proper ProConnect logout (requires id_token_hint)
      //
      // Security: Authorization is enforced in multiple layers:
      // 1. JWT callback marks unauthorized users (token.unauthorized = true)
      // 2. useAuth() returns isAuthenticated = false for unauthorized users
      // 3. AuthorizationCheck redirects unauthorized users to /access-denied
      //
      // This approach prevents the "user jail" problem while maintaining security
      return true;
    },
    async jwt({ token, account, profile, user }) {
      // Persist the OAuth tokens and profile after signin
      if (account) {
        token.accessToken = account.access_token;
        token.idToken = account.id_token;
      }
      if (profile) {
        token.profile = profile as ProConnectProfile;

        // Check if the user's email domain is allowed
        const email = profile.email || user?.email;
        if (!isEmailDomainAllowed(email)) {
          token.unauthorized = true;
        }

        // Compute beta tester flag server-side (do not expose the list)
        token.isBetaTester = isBetaTesterEmail(email);
      }
      return token;
    },
    async session({ session, token }) {
      // Pass tokens and profile to the client session
      session.accessToken = token.accessToken as string;
      session.idToken = token.idToken as string;
      session.profile = token.profile as ProConnectProfile | undefined;
      session.unauthorized = token.unauthorized as boolean | undefined;
      session.isBetaTester = token.isBetaTester as boolean | undefined;
      return session;
    },
  },
  pages: {
    signIn: "/",
    error: "/access-denied",
  },
  events: {
    async signIn({ user }) {
      Sentry.setUser({
        id: user.id,
        email: user.email || undefined,
      });
    },
    async signOut() {
      Sentry.setUser(null);
    },
  },
};
