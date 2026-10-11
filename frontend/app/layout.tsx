import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Hisaab: AP Agent",
  description: "Accounts payable agent powered by Sarvam Vision and Sarvam-105B",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} font-sans antialiased`}>
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
            <Link href="/" className="flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-orange-500 to-indigo-600 font-bold text-white">
                ₹
              </span>
              <span className="text-lg font-semibold tracking-tight">Hisaab</span>
              <span className="hidden text-sm text-slate-500 sm:inline">· Accounts Payable Agent</span>
            </Link>
            <span className="text-xs text-slate-500">
              powered by <b className="text-slate-700">Sarvam Vision</b> + <b className="text-slate-700">Sarvam-105B</b>
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
