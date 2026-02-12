import { getServerSession } from "next-auth";
import { authOptions } from "./auth-options";

/**
 * Returns the session only if the user is authenticated AND authorized.
 * Returns null if no session or if the user's email domain is not allowed.
 */
export async function getAuthorizedSession() {
  const session = await getServerSession(authOptions);
  if (!session || session.unauthorized) return null;
  return session;
}
