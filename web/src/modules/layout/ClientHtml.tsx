"use client";

import { ReactNode } from "react";
import { getHtmlAttributes } from "@codegouvfr/react-dsfr/next-appdir/getHtmlAttributes";
import { DsfrHead } from "@codegouvfr/react-dsfr/next-appdir/DsfrHead";
import { DsfrProvider } from "@codegouvfr/react-dsfr/next-appdir/DsfrProvider";
import { defaultColorScheme } from "@/modules/dsfr/defaultColorScheme";
import { StartDsfr } from "@/modules/dsfr/StartDsfr";
import { SessionProvider } from "next-auth/react";
import Link from "next/link";
import Head from "next/head";
import Matomo from "@/modules/common/Matomo";

export function ClientHtml({
  children,
  lang,
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
        <SessionProvider>
          <DsfrProvider lang={lang}>{children}</DsfrProvider>
          <Matomo />
        </SessionProvider>
      </body>
    </html>
  );
}
