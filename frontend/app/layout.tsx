export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // [locale]/layout.tsx handles the actual HTML shell.
  // This root layout is required by Next.js but [locale] layout takes precedence.
  return children as React.ReactElement;
}
