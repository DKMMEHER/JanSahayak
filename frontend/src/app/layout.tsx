import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Jan Sahayak (जन सहायक) — AI Government Scheme Finder",
  description:
    "Chat or speak in regional Indic languages to dynamically discover matching welfare schemes, verify eligibility, and get step-by-step application guidance.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased dark`} suppressHydrationWarning>
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#0a0e1a" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  navigator.serviceWorker.register('/sw.js').then(function(reg) {
                    console.log('Service Worker registered with scope:', reg.scope);
                  }).catch(function(err) {
                    console.error('Service Worker registration failed:', err);
                  });
                });
              }
            `,
          }}
        />
      </head>
      <body className="min-h-full flex flex-col bg-[#0a0e1a] text-slate-100 selection:bg-orange-500/30 selection:text-orange-200">
        {children}
      </body>
    </html>
  );
}
