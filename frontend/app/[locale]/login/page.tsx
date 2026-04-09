import { Suspense } from "react";
import AuthForm from "@/src/components/auth/AuthForm";

export default function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-muted">
      <Suspense>
        <AuthForm />
      </Suspense>
    </main>
  );
}
