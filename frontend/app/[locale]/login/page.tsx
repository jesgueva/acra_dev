import { Suspense } from "react";
import AuthForm from "@/src/components/auth/AuthForm";
import AcraLogo from "@/src/components/brand/AcraLogo";
import { Cpu } from "lucide-react";

export default function LoginPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-background">
      <div className="absolute inset-0 login-bg-grid opacity-60" />
      <div className="absolute inset-0 login-bg-gradient" />

      <div className="relative flex min-h-screen">
        {/* Left panel — branding (lg+) */}
        <div className="hidden lg:flex lg:w-[52%] flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15">
              <Cpu className="h-5 w-5 text-primary" />
            </div>
            <span className="font-heading text-base font-semibold text-foreground">ACRA MES</span>
          </div>

          <div className="space-y-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary mb-3">
                Manufacturing Execution System
              </p>
              <h2 className="font-heading text-5xl font-bold leading-tight text-foreground">
                Operations
                <br />
                Control Center
              </h2>
            </div>
            <p className="max-w-md text-base text-muted-foreground leading-relaxed">
              Real-time inventory tracking, work order management, and lot
              traceability — built for the factory floor.
            </p>

            <ul className="space-y-3">
              {[
                "OCR-powered receiving workflow",
                "Live inventory & stock alerts",
                "Work order lifecycle tracking",
                "Role-based access control",
              ].map((feature) => (
                <li key={feature} className="flex items-center gap-3 text-sm text-muted-foreground">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                  {feature}
                </li>
              ))}
            </ul>
          </div>

          <p className="text-xs text-muted-foreground/50">
            ACRA Integrated MES · Phase 1–3 · v2.1
          </p>
        </div>

        {/* Right panel — login form */}
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 lg:px-16">
          <div className="mb-8 lg:hidden">
            <AcraLogo size="login" />
          </div>

          <div className="w-full max-w-sm">
            <div className="mb-8 hidden lg:block">
              <AcraLogo size="header" />
              <p className="mt-4 text-2xl font-heading font-semibold text-foreground">
                Sign in to your account
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Enter your credentials to access the system.
              </p>
            </div>

            <Suspense>
              <AuthForm />
            </Suspense>
          </div>
        </div>
      </div>
    </main>
  );
}
