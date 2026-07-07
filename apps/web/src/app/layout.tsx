import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Sales Teammate",
  description: "AI-powered B2B sales and marketing platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
