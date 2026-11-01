import type { Metadata } from "next";
import { ReactNode } from "react";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "RITEN-GRAPH",
  description: "Explore how semiconductor trade, technology restrictions and national AI infrastructure relate, 2015–2025.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
