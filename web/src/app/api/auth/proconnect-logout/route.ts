import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth/auth-options";
import { buildProConnectLogoutUrl } from "@/lib/auth/proconnect-logout";

/**
 * Returns the ProConnect logout URL for the current session.
 * Built server-side: the ProConnect domain depends on PROCONNECT_ENV, which is
 * only available at runtime on the server (not in the browser bundle).
 */
export async function GET(request: NextRequest) {
  const session = await getServerSession(authOptions);
  const postLogoutRedirectUri = request.nextUrl.searchParams.get(
    "post_logout_redirect_uri"
  );

  // The URL carries the id_token: never cache it
  const headers = { "Cache-Control": "no-store" };

  if (!session?.idToken || !postLogoutRedirectUri) {
    return NextResponse.json({ url: null }, { headers });
  }

  return NextResponse.json(
    { url: buildProConnectLogoutUrl(session.idToken, postLogoutRedirectUri) },
    { headers }
  );
}
