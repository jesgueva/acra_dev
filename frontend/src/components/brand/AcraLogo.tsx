import Image from "next/image";
import acraLogo from "@/acra_logo.png";

interface AcraLogoProps {
  size?: "header" | "login";
}

export default function AcraLogo({ size = "header" }: AcraLogoProps) {
  if (size === "login") {
    return (
      <div className="flex flex-col items-center gap-3">
        <div className="rounded-2xl border border-border/40 bg-white px-8 py-5 shadow-md">
          <Image
            src={acraLogo}
            alt="ACRAPACK logo"
            priority
            className="h-auto w-[260px] max-w-full"
          />
        </div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
          Manufacturing Execution System
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border/40 bg-white px-3 py-1.5 shadow-sm">
      <Image
        src={acraLogo}
        alt="ACRAPACK logo"
        priority
        className="h-auto w-[140px]"
      />
    </div>
  );
}
