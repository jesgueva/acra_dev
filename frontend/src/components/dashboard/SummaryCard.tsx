import { type LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface SummaryCardProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
}

export function SummaryCard({ icon: Icon, label, value }: SummaryCardProps) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-6">
        <Icon className="h-8 w-8 shrink-0 text-muted-foreground" aria-hidden />
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}
