import { signOut } from "next-auth/react";

/**
 * Sign out from NextAuth, then from ProConnect.
 * Falls back to a local sign out when no ProConnect logout URL is available.
 */
export async function signOutWithProConnect() {
  try {
    const params = new URLSearchParams({
      // Without trailing slash to match ProConnect config
      post_logout_redirect_uri: window.location.origin,
    });
    const response = await fetch(`/api/auth/proconnect-logout?${params}`);
    const { url } = response.ok ? await response.json() : { url: null };

    if (url) {
      // Clear NextAuth session first, then redirect to ProConnect logout
      await signOut({ redirect: false });
      window.location.href = url;
      return;
    }
  } catch (error) {
    console.error("❌ Error signing out:", error);
  }

  await signOut({ callbackUrl: "/" });
}
