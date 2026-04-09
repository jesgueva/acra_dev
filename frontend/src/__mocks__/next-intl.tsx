import React from "react";

export const useTranslations = (namespace?: string) => {
  return (key: string) => (namespace ? `${namespace}.${key}` : key);
};

export const useLocale = () => "en";

export const NextIntlClientProvider = ({
  children,
}: {
  children: React.ReactNode;
  messages?: Record<string, unknown>;
  locale?: string;
}) => <>{children}</>;
