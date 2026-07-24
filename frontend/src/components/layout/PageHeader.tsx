import type { ReactNode } from "react";
import { Separator } from "@/components/ui/separator";

interface PageHeaderProps {
  title: string;
  description?: string;
  children?: ReactNode;
}

export function PageHeader({ title, description, children }: PageHeaderProps) {
  return (
    <div className="bg-card/40 px-6 pt-5 pb-0">
      <div className="flex items-start justify-between gap-4 pb-5">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {title}
          </h1>
          {description && (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {children && (
          <div className="flex shrink-0 items-center gap-2 pt-0.5">{children}</div>
        )}
      </div>
      <Separator />
    </div>
  );
}
