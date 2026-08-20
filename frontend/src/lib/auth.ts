import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

// The credentials provider does not check a password itself -- it forwards
// email/password to the FastAPI backend's /auth/login, which is the only
// place password hashes exist. NextAuth's job here is session handling
// (the JWT it issues), not authentication itself.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const { handlers, signIn, signOut, auth } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      authorize: async (credentials) => {
        const res = await fetch(`${API_URL}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: credentials?.email,
            password: credentials?.password,
          }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        return {
          id: String(data.user.id),
          email: data.user.email,
          name: data.user.display_name,
          // Carried through to the JWT/session below so client requests to
          // the FastAPI backend can attach it as a Bearer token.
          accessToken: data.access_token,
        };
      },
    }),
  ],
  callbacks: {
    jwt: async ({ token, user }) => {
      if (user) {
        token.accessToken = (user as { accessToken?: string }).accessToken;
      }
      return token;
    },
    session: async ({ session, token }) => {
      (session as { accessToken?: string }).accessToken = token.accessToken as string;
      return session;
    },
    // Without this, `auth` used as proxy.ts's export only ATTACHES session
    // data to the request -- it does not deny anything on its own. Returning
    // false here is what actually redirects an unauthenticated request to
    // /login (verified: curl with no session cookie was reaching "/" and
    // rendering the page before this callback was added).
    authorized: ({ auth: session }) => Boolean(session),
  },
});
