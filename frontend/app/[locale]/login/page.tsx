import { Suspense } from "react";
import AuthForm from "@/src/components/auth/AuthForm";
import AcraLogo from "@/src/components/brand/AcraLogo";

export default function LoginPage() {
  return (
    <main className="min-h-screen bg-muted">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col items-center justify-center gap-8 px-6 py-10">
        <AcraLogo size="login" />
        <Suspense>
          <AuthForm />
        </Suspense>
      </div>
    </main>
  );
}
