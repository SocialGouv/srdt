import { NextRequest } from "next/server";
import { timingSafeEqual } from "crypto";

export function hasValidDebugToken(request: NextRequest): boolean {
  const expected = process.env.DEBUG_API_KEY;
  if (!expected) return false;

  const header = request.headers.get("authorization");
  if (!header?.startsWith("Bearer ")) return false;
  const provided = header.slice("Bearer ".length).trim();
  if (!provided) return false;

  const providedBuf = Buffer.from(provided);
  const expectedBuf = Buffer.from(expected);
  if (providedBuf.length !== expectedBuf.length) return false;
  return timingSafeEqual(providedBuf, expectedBuf);
}
