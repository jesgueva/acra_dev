import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export interface AlertItem {
  material_name: string;
  quantity: number;
  threshold: number;
  is_triggered: boolean;
}

interface AlertBannerProps {
  alerts: AlertItem[];
}

export function AlertBanner({ alerts }: AlertBannerProps) {
  const triggered = alerts.filter((a) => a.is_triggered);
  if (triggered.length === 0) return null;

  const count = triggered.length;
  const names = triggered.map((a) => a.material_name).join(", ");

  return (
    <Alert variant="destructive">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>
        {count === 1 ? "Low Stock Alert" : `${count} Low Stock Alerts`}
      </AlertTitle>
      <AlertDescription>
        {names}{" "}
        {count === 1 ? "is" : "are"} below the configured threshold.
      </AlertDescription>
    </Alert>
  );
}
