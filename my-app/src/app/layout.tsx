import type { Metadata } from "next";
import "./globals.css";
import "./theme.css";
import "./panel.css";
import "./chrome.css";
import "./polish.css";
import RippleGrid from "@/components/RippleGrid";

export const metadata: Metadata = {
  title: "IntentFlow",
  description: "Functional intent graph for legacy codebase modernization",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" />
      </head>
      <body suppressHydrationWarning>
        <RippleGrid />
        {children}
      </body>
    </html>
  );
}
