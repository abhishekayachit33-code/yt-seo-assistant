import { auth, signOut } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { Workspace, type HistoryItem } from "@/components/Workspace";

export default async function Home() {
  const session = await auth();
  const accessToken = (session as { accessToken?: string } | null)?.accessToken;

  let history: HistoryItem[] = [];
  let historyError: string | null = null;
  try {
    history = await apiFetch<HistoryItem[]>("/history", accessToken);
  } catch (err) {
    historyError = err instanceof Error ? err.message : "Failed to load history.";
  }

  return (
    <main className="mx-auto max-w-4xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">YouTube SEO Studio</h1>
        <form
          action={async () => {
            "use server";
            await signOut();
          }}
        >
          <button type="submit" className="text-sm underline">
            Sign out ({session?.user?.name})
          </button>
        </form>
      </div>

      {historyError && <p className="mb-4 text-sm text-red-600">{historyError}</p>}

      <Workspace accessToken={accessToken} history={history} />
    </main>
  );
}
