import { Geist } from "next/font/google";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // [locale]/layout.tsx handles the actual HTML shell.
  return <div className={geist.variable}>{children as React.ReactElement}</div>;
}
