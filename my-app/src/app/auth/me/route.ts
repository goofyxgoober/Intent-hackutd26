import { NextResponse, type NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  try {
    const res = await fetch(`${BACKEND}/auth/me`, {
      headers: {
        cookie: request.headers.get("cookie") ?? "",
      },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(null, { status: res.status });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    // Backend offline / not reachable: return 401 unauthenticated without crashing proxy
    return NextResponse.json(null, { status: 401 });
  }
}
