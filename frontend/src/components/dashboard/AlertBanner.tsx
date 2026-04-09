import { AlertTriangle } from "lucide-react";

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

  return (
    <div
      role="alert"
      className="flex items-center gap-3 rounded-md border border-yellow-400 bg-yellow-100 px-4 py-3 text-yellow-800"
    >
      <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden />
      <span>
        <strong>Low Stock Alert:</strong>{" "}
        {triggered.map((a) => a.material_name).join(", ")} below threshold.
      </span>
    </div>
  );
}
