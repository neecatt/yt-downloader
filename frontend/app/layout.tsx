import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Downloader Admin",
  description: "Private activity dashboard for the Telegram downloader bot",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
