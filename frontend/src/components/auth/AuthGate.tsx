"use client";

import { useEffect } from "react";
import { useLocale } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/src/contexts/AuthContext";
import { registerNavigateHandler } from "@/src/lib/api-client";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, authResolved } = useAuth();

  const loginPath = `/${locale}/login`;
  const isLoginPage = pathname === loginPath;

  useEffect(() => {
    registerNavigateHandler((path) => {
      const localePath = path.startsWith("/") ? `/${locale}${path}` : path;
      router.push(localePath);
    });
  }, [locale, router]);

  useEffect(() => {
    if (authResolved && !isAuthenticated && !isLoginPage) {
      router.replace(loginPath);
    }
  }, [authResolved, isAuthenticated, isLoginPage, loginPath, router]);

  if (isLoginPage) {
    return <>{children}</>;
  }

  if (!authResolved || !isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
