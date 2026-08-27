import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ACUD ATS",
  description:
    "Read each CV once, match it against any vacancy, and see the reasons behind every result.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
