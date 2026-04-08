import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ACRA MES",
  description: "ACRA Integrated Manufacturing Execution System",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
