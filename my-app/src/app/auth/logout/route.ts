import { NextResponse, type NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  try {
    const res = await fetch(`${BACKEND}/auth/logout`, {
      method: "POST",
      headers: {
        cookie: request.headers.get("cookie") ?? "",
      },
    });
    const nextRes = new NextResponse(null, { status: res.status });
    const setCookie = res.headers.get("set-cookie");
    if (setCookie) nextRes.headers.set("set-cookie", setCookie);
    return nextRes;
  } catch {
    return new NextResponse(null, { status: 204 });
  }
}
