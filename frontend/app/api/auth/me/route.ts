import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { AUTH_COOKIE } from "@/src/lib/auth-cookie";

const BACKEND_URL =
  process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET() {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE)?.value;

  if (!token) {
    return NextResponse.json({ error: "No session" }, { status: 401 });
  }

  const backendRes = await fetch(`${BACKEND_URL}/api/v1/users/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!backendRes.ok) {
    return NextResponse.json({ error: "Invalid session" }, { status: 401 });
  }

  const user = await backendRes.json();
  return NextResponse.json({ access_token: token, user });
}
