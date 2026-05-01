import AppShowcase from "@/components/public/AppShowcase";
import Hero from "@/components/public/Hero";
import Triptych from "@/components/public/Triptych";

export const dynamic = "force-static";

export default function PublicHomePage() {
  return (
    <>
      <Hero />
      <AppShowcase />
      <Triptych />
    </>
  );
}
