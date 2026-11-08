import { NextResponse, type NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  try {
    const search = request.nextUrl.search;
    const res = await fetch(`${BACKEND}/auth/github/login${search}`, {
      redirect: "manual",
    });
    const location = res.headers.get("location");
    if (location) {
      const targetUrl = location.startsWith("http") ? location : new URL(location, request.url).toString();
      const redirect = NextResponse.redirect(targetUrl, { status: 307 });
      const setCookies = typeof res.headers.getSetCookie === "function" 
        ? res.headers.getSetCookie() 
        : [res.headers.get("set-cookie")].filter(Boolean) as string[];
      for (const cookie of setCookies) {
        redirect.headers.append("set-cookie", cookie);
      }
      return redirect;
    }
    if (res.status === 500) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail || "github_not_configured";
      return NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(detail)}`, request.url));
    }
    return NextResponse.redirect(new URL("/login?error=backend_offline", request.url));
  } catch {
    return NextResponse.redirect(new URL("/login?error=backend_offline", request.url));
  }
}
