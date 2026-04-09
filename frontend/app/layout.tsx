import "./globals.css";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // [locale]/layout.tsx handles the HTML shell including font and lang.
  return children as React.ReactElement;
}
