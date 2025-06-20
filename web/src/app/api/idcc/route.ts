import { NextRequest, NextResponse } from "next/server";
import * as Sentry from "@sentry/nextjs";

const SITE_URL = "https://code.travail.gouv.fr";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const query = searchParams.get("q");
  const size = searchParams.get("size");

  if (!query) {
    return NextResponse.json(
      { error: "Query parameter is required" },
      { status: 400 }
    );
  }

  try {
    // Build the URL for the external API
    let url = `${SITE_URL}/api/idcc?q=${encodeURIComponent(query)}`;

    if (size) {
      url += `&size=${encodeURIComponent(size)}`;
    }

    // Make the request to the external API
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`External API returned ${response.status}`);
    }

    const data = await response.json();

    // Return the data with proper CORS headers
    return NextResponse.json(data, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
      },
    });
  } catch (error) {
    Sentry.captureException(error, {
      tags: {
        endpoint: "/api/idcc",
      },
      extra: {
        method: "GET",
        query: query,
        size: size,
        externalUrl: `${SITE_URL}/api/idcc`,
      },
    });
    console.error("Error proxying request to code.travail.gouv.fr:", error);
    return NextResponse.json(
      { error: "Ce service est momentanément indisponible." },
      { status: 500 }
    );
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 200,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}
