import type { Metadata } from "next";
import { Providers } from "./providers";
import { Header } from "@/components/Header";
import "./globals.css";

export const metadata: Metadata = {
  title: "链上套利助手 | Chain Arbitrage Assistant",
  description: "多链、多策略的链上套利分析系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>
          <Header />
          <main className="lg:pl-64 pt-16 lg:pt-0">
            <div className="container mx-auto p-4 lg:p-6">
              {children}
            </div>
          </main>
        </Providers>
      </body>
    </html>
  );
}
