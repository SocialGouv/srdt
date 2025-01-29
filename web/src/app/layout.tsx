import type { Metadata } from "next";
import { DsfrHead } from "@codegouvfr/react-dsfr/next-appdir/DsfrHead";
import { DsfrProvider } from "@codegouvfr/react-dsfr/next-appdir/DsfrProvider";
import { getHtmlAttributes } from "@codegouvfr/react-dsfr/next-appdir/getHtmlAttributes";
import Link from "next/link";
import { defaultColorScheme } from "@/modules/dsfr/defaultColorScheme";
import { StartDsfr } from "@/modules/dsfr/StartDsfr";
import { AuthProvider } from "@/hooks/use-auth";

export const metadata: Metadata = {
  title: "SRDT",
  description: "Experimentation IA pour les SRDT",
  robots: "noindex, nofollow",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const lang = "fr";
  return (
    <html {...getHtmlAttributes({ defaultColorScheme, lang })}>
      <head>
        <StartDsfr />
        <DsfrHead
          Link={Link}
          preloadFonts={[
            "Marianne-Regular",
            "Marianne-Medium",
            "Marianne-Bold",
          ]}
        />
      </head>
      <body>
        <AuthProvider>
          <DsfrProvider lang={lang}>{children}</DsfrProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
