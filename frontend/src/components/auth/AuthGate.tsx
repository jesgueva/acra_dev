"use client";

import { useEffect } from "react";
import { useLocale } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/src/contexts/AuthContext";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, authResolved } = useAuth();

  const loginPath = `/${locale}/login`;
  const isLoginPage = pathname === loginPath;

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
