"use client";

import { ReactNode } from "react";
import { getHtmlAttributes } from "@codegouvfr/react-dsfr/next-appdir/getHtmlAttributes";
import { DsfrHead } from "@codegouvfr/react-dsfr/next-appdir/DsfrHead";
import { DsfrProvider } from "@codegouvfr/react-dsfr/next-appdir/DsfrProvider";
import { defaultColorScheme } from "@/modules/dsfr/defaultColorScheme";
import { StartDsfr } from "@/modules/dsfr/StartDsfr";
import { AuthProvider } from "@/hooks/use-auth";
import Link from "next/link";
import Head from "next/head";

export function ClientHtml({
  children,
  lang
}: {
  children: ReactNode;
  lang: string;
}) {
  return (
    <html {...getHtmlAttributes({ defaultColorScheme, lang })}>
      <Head>
        <StartDsfr />
        <DsfrHead
          Link={Link}
          preloadFonts={[
            "Marianne-Regular",
            "Marianne-Medium",
            "Marianne-Bold",
          ]}
        />
      </Head>
      <body>
        <AuthProvider>
          <DsfrProvider lang={lang}>
            {children}
          </DsfrProvider>
        </AuthProvider>
      </body>
    </html>
  );
}