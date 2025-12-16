import { NextAuthOptions } from "next-auth";
import ProConnectProvider, { ProConnectProfile } from "./ProConnectProvider";
import * as Sentry from "@sentry/nextjs";

// Allowed email domains for access control
const ALLOWED_EMAIL_DOMAINS = [
  "pyrenees-atlantiques.gouv.fr",
  "seine-maritime.gouv.fr",
  "correze.gouv.fr",
  "dreets.gouv.fr",
  "travail.gouv.fr",
  "fabrique.social.gouv.fr",
  "sg.social.gouv.fr",
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
      }
      return token;
    },
    async session({ session, token }) {
      // Pass tokens and profile to the client session
      session.accessToken = token.accessToken as string;
      session.idToken = token.idToken as string;
      session.profile = token.profile as ProConnectProfile | undefined;
      session.unauthorized = token.unauthorized as boolean | undefined;
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
