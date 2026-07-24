"use client";

import { usePathname } from "next/navigation";
import { useLocale } from "next-intl";
import NavSidebar from "@/src/components/layout/NavSidebar";
import MobileNav from "@/src/components/layout/MobileNav";
import { cn } from "@/lib/utils";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const locale = useLocale();
  const pathname = usePathname();
  const hasSidebar = pathname !== `/${locale}/login`;

  return (
    <div className="flex min-h-screen bg-background">
      <NavSidebar />
      {/* The 256px offset applies only from `md` up, where the sidebar is actually rendered.
          Applied unconditionally it left ~134px of usable width on a 390px phone (NFR-010).
          `min-w-0` lets wide children shrink instead of forcing the page to scroll sideways. */}
      <div className={cn("flex min-h-screen min-w-0 flex-1 flex-col", hasSidebar && "md:ml-64")}>
        <MobileNav />
        {children}
      </div>
    </div>
  );
}
