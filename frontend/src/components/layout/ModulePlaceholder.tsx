import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export type PlaceholderFeature = {
  icon: LucideIcon;
  title: string;
  description: string;
};

export function ComingSoonBadge({ label }: { label: string }) {
  return (
    <Badge variant="outline" className="gap-1.5 border-primary/40 bg-primary/10 text-primary">
      <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
      {label}
    </Badge>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="mb-4 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </p>
  );
}

export function ModuleBanner({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/12">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription className="mt-1">{description}</CardDescription>
          </div>
        </div>
      </CardHeader>
    </Card>
  );
}

export function FeatureGrid({ features }: { features: PlaceholderFeature[] }) {
  return (
    <div>
      <SectionLabel>Upcoming Features</SectionLabel>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {features.map((feature) => (
          <Card key={feature.title}>
            <CardContent className="flex items-start gap-4 p-5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <feature.icon className="h-4 w-4 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">{feature.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">
                  {feature.description}
                </p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function RequirementsBar({ requirements }: { requirements: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted-foreground mr-1">Requirements:</span>
      {requirements.map((ref) => (
        <Badge key={ref} variant="outline" className="font-mono text-xs">
          {ref}
        </Badge>
      ))}
    </div>
  );
}
