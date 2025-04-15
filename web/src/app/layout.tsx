import type { Metadata } from "next";
import { ClientHtml } from "@/modules/layout/ClientHtml";

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
  return <ClientHtml lang={lang}>{children}</ClientHtml>;
}
