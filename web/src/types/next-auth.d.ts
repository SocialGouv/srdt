import { DefaultSession } from "next-auth";
import { ProConnectProfile } from "@/lib/auth/ProConnectProvider";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    idToken?: string;
    profile?: ProConnectProfile;
    unauthorized?: boolean;
    isBetaTester?: boolean;
    user: {
      id: string;
    } & DefaultSession["user"];
  }

  interface User {
    given_name?: string;
    family_name?: string;
    siret?: string;
    organizational_unit?: string;
    belonging_population?: string;
    phone_number?: string;
    job?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    idToken?: string;
    profile?: ProConnectProfile;
    unauthorized?: boolean;
    isBetaTester?: boolean;
  }
}
