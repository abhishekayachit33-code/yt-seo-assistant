"use client";

import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { signup } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await signup(email, password, displayName);
      const result = await signIn("credentials", { email, password, redirect: false });
      if (result?.error) throw new Error("Account created, but sign-in failed. Try signing in manually.");
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-lg border p-6">
        <h1 className="text-xl font-semibold">Create an account</h1>
        <input
          type="text" placeholder="Your name" value={displayName} required
          onChange={(e) => setDisplayName(e.target.value)}
          className="w-full rounded border px-3 py-2"
        />
        <input
          type="email" placeholder="Email" value={email} required
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded border px-3 py-2"
        />
        <input
          type="password" placeholder="Password (min 8 characters)" value={password} required minLength={8}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded border px-3 py-2"
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit" disabled={loading}
          className="w-full rounded bg-black px-3 py-2 text-white disabled:opacity-50"
        >
          {loading ? "Creating account..." : "Sign up"}
        </button>
      </form>
    </main>
  );
}
