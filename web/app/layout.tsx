import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  // The tab is a working surface, not a landing page: the run's own title is
  // set per page and this is what wraps it.
  title: {
    default: "True Story · Fact and rights engine",
    template: "%s · True Story",
  },
  description:
    "A fact and rights engine for based on a true story productions. Every claim checked against the record, every element cleared to insurer standard.",
  applicationName: "True Story",
  // A clearance workspace holds unpublished drafts and assertions about named
  // living people. It is not a page that wants an index entry.
  robots: { index: false, follow: false },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
  },
};

export const viewport: Viewport = {
  // Matches --bg, so the mobile browser chrome does not sit as a bright band
  // above a near black instrument.
  themeColor: "#090c11",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
