import { NextRequest, NextResponse } from "next/server";

// The browser only talks to this origin. The API address stays on the server and out of client bundles.
const passResponseHeaders = ["content-type", "set-cookie", "x-cache", "x-request-id"];

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:18000";
  const { path } = await context.params;
  const target = `${base}/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of ["cookie", "content-type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = !["GET", "HEAD"].includes(request.method);
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
    const responseHeaders = new Headers();
    for (const name of passResponseHeaders) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
    return new NextResponse(body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: "The API is not reachable." }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
