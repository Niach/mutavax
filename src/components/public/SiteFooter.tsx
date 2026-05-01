import Link from "next/link";

export default function SiteFooter() {
  return (
    <footer className="site">
      <div className="brand">
        <span className="dot" />mutavax · v0.6
      </div>
      <div className="links">
        <Link href="/">Overview</Link>
        <a href="https://github.com/niach/mutavax" target="_blank" rel="noreferrer">GitHub</a>
      </div>
    </footer>
  );
}
