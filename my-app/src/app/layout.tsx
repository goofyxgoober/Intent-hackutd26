import type { Metadata } from "next";
import "./globals.css";
import "./theme.css";
import "./panel.css";
import "./chrome.css";
import ChalkBoard from "@/components/ChalkBoard";

export const metadata: Metadata = {
  title: "IntentFlow",
  description: "Functional intent graph for legacy codebase modernization",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;500&family=JetBrains+Mono:wght@400;500;600&display=swap" />
      </head>
      <body>
        <ChalkBoard />
        {children}
      </body>
    </html>
  );
}
