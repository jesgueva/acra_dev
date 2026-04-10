import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getLocale } from "next-intl/server";
import AuthGate from "@/src/components/auth/AuthGate";
import { AuthProvider } from "@/src/contexts/AuthContext";
import AppShell from "@/src/components/layout/AppShell";
import { QueryProvider } from "@/src/components/providers/QueryProvider";

export default async function LocaleLayout({
  children,
}: {
  children: ReactNode;
}) {
  const [locale, messages] = await Promise.all([getLocale(), getMessages()]);

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <QueryProvider>
        <AuthProvider>
          <AppShell>
            <AuthGate>{children}</AuthGate>
          </AppShell>
        </AuthProvider>
      </QueryProvider>
    </NextIntlClientProvider>
  );
}
