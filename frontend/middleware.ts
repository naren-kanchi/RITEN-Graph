import { NextRequest, NextResponse } from "next/server";

// A convenience redirect only. The API checks the session and role on every request.
export function middleware(request: NextRequest) {
  if (!request.cookies.has("riten_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!login|api|_next|favicon.ico).*)"],
};
