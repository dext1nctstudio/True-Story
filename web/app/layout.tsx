import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TRUE STORY",
  description:
    "A fact and rights engine for based on a true story productions. Every claim checked against the record, every element cleared to insurer standard.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
