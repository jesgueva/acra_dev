"use client";

import { usePathname } from "next/navigation";
import { useLocale } from "next-intl";
import NavSidebar from "@/src/components/layout/NavSidebar";
import { cn } from "@/lib/utils";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const locale = useLocale();
  const pathname = usePathname();
  const hasSidebar = pathname !== `/${locale}/login`;

  return (
    <div className="flex min-h-screen bg-background">
      <NavSidebar />
      <div className={cn("flex flex-1 flex-col min-h-screen", hasSidebar && "ml-64")}>
        {children}
      </div>
    </div>
  );
}
