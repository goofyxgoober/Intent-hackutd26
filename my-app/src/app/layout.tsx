import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IntentFlow",
  description: "Functional intent graph for legacy codebase modernization",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat&display=swap" />
      </head>
      <body>{children}</body>
    </html>
  );
}
