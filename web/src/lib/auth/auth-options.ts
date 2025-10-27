import { NextAuthOptions } from "next-auth";
import ProConnectProvider, { ProConnectProfile } from "./ProConnectProvider";
import * as Sentry from "@sentry/nextjs";

// Debug logging
console.log("🔧 NextAuth Configuration:");
console.log("  PROCONNECT_ENV:", process.env.PROCONNECT_ENV);
console.log(
  "  PROCONNECT_CLIENT_ID:",
  process.env.PROCONNECT_CLIENT_ID ? "✓ Set" : "✗ Missing"
);
console.log(
  "  PROCONNECT_CLIENT_SECRET:",
  process.env.PROCONNECT_CLIENT_SECRET ? "✓ Set" : "✗ Missing"
);
console.log("  NEXTAUTH_URL:", process.env.NEXTAUTH_URL);
console.log(
  "  NEXTAUTH_SECRET:",
  process.env.NEXTAUTH_SECRET ? "✓ Set" : "✗ Missing"
);

export const authOptions: NextAuthOptions = {
  providers: [
    ProConnectProvider({
      clientId: process.env.PROCONNECT_CLIENT_ID!,
      clientSecret: process.env.PROCONNECT_CLIENT_SECRET!,
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      console.log("📝 JWT Callback:", {
        hasAccount: !!account,
        hasProfile: !!profile,
      });
      // Persist the OAuth access_token and profile to the token right after signin
      if (account) {
        console.log("  Account type:", account.provider);
        token.accessToken = account.access_token;
        token.idToken = account.id_token;
      }
      if (profile) {
        console.log("  Profile email:", profile.email);
        token.profile = profile as ProConnectProfile;
      }
      return token;
    },
    async session({ session, token }) {
      console.log("🔐 Session Callback:", {
        hasToken: !!token,
        hasUser: !!session.user,
      });
      // Send properties to the client
      session.accessToken = token.accessToken as string;
      session.idToken = token.idToken as string;
      session.profile = token.profile as ProConnectProfile | undefined;
      return session;
    },
  },
  pages: {
    signIn: "/",
    error: "/",
  },
  events: {
    async signIn({ user }) {
      console.log("✅ Sign in event:", user.email);
      Sentry.setUser({
        id: user.id,
        email: user.email || undefined,
      });
    },
    async signOut() {
      console.log("👋 Sign out event");
      Sentry.setUser(null);
    },
  },
  logger: {
    error(code, metadata) {
      console.error("❌ NextAuth Error:", code, metadata);
    },
    warn(code) {
      console.warn("⚠️  NextAuth Warning:", code);
    },
    debug(code, metadata) {
      console.log("🐛 NextAuth Debug:", code, metadata);
    },
  },
  debug: true,
};
