import Image from "next/image";
import acraLogo from "@/acra_logo.png";

interface AcraLogoProps {
  size?: "header" | "login";
}

export default function AcraLogo({ size = "header" }: AcraLogoProps) {
  if (size === "login") {
    return (
      <div className="flex flex-col items-center gap-3">
        <div className="rounded-3xl border border-border/60 bg-background/90 px-6 py-4 shadow-sm">
          <Image
            src={acraLogo}
            alt="ACRAPACK logo"
            priority
            className="h-auto w-[320px] max-w-full"
          />
        </div>
        <p className="text-sm font-medium tracking-[0.16em] text-muted-foreground">
          Manufacturing Execution System
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border/60 bg-background/90 px-3 py-2 shadow-sm">
      <Image
        src={acraLogo}
        alt="ACRAPACK logo"
        priority
        className="h-auto w-[180px]"
      />
    </div>
  );
}
