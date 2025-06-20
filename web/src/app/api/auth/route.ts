import { NextResponse } from "next/server";
import * as Sentry from "@sentry/nextjs";

export async function POST(request: Request) {
  try {
    const { code } = await request.json();

    if (code !== process.env.APP_ACCESS_KEY) {
      return NextResponse.json(
        { message: "Code d'accès invalide" },
        { status: 401 }
      );
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    Sentry.captureException(error, {
      tags: {
        endpoint: "/api/auth",
      },
      extra: {
        method: "POST",
      },
    });
    console.error(error);
    return NextResponse.json(
      { message: "Erreur lors de la vérification" },
      { status: 500 }
    );
  }
}
