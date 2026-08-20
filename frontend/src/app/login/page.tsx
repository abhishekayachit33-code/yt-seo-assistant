"use client";

import { signIn } from "next-auth/react";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const result = await signIn("credentials", { email, password, redirect: false });
    setLoading(false);
    if (result?.error) {
      setError("Incorrect email or password.");
      return;
    }
    router.push("/");
  }

  return (
    <main className="flex min-h-screen items-center justify-center">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-lg border p-6">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <input
          type="email" placeholder="Email" value={email} required
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded border px-3 py-2"
        />
        <input
          type="password" placeholder="Password" value={password} required
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded border px-3 py-2"
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit" disabled={loading}
          className="w-full rounded bg-black px-3 py-2 text-white disabled:opacity-50"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
        <p className="text-sm text-gray-500">
          No account? <Link href="/signup" className="underline">Sign up</Link>
        </p>
      </form>
    </main>
  );
}
