export { auth as proxy } from "@/lib/auth";

// Everything except the auth API routes, the login/signup pages, and Next's
// own static/internal assets requires a signed-in session.
//
// Named `proxy`, not `middleware` -- Next.js 16 renamed the file convention
// (middleware.ts is deprecated in favor of proxy.ts, same behavior).
export const config = {
  matcher: ["/((?!api/auth|login|signup|_next/static|_next/image|favicon.ico).*)"],
};
