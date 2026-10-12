import { HomeContent } from "@/modules/home/HomeContent";
import { getNouveautesVersion } from "@/modules/nouveautes/version";

export default function Home() {
  return <HomeContent nouveautesVersion={getNouveautesVersion()} />;
}
