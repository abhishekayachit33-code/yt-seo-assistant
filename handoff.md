# Handoff — YouTube SEO Assistant + GitOps Pipeline

Last updated: 2026-08-13. Read this top-to-bottom before touching anything —
the "Act on this first" section is not optional.

---

## 0. Act on this first

**Minikube/Docker/Jenkins/ngrok are all down right now** (confirmed live
while updating this doc — `kubectl` refuses to connect, Jenkins/ngrok both
000). Same recurring failure mode as before: none of these auto-start, and
they go down every time this laptop sleeps or reboots. To recover, in order:
`open -a Docker` and wait for `docker info` to succeed, `minikube start`,
start Jenkins as a foreground process (see §5 for why not the brew service),
start `ngrok http 8080`, then check whether the GitHub webhook URL still
matches the ngrok tunnel (it rotates on every restart on the free tier) —
`gh api repos/abhishekayachit33-code/yt-seo-assistant/hooks` shows the
current registered URL.

**Separately, there is substantial uncommitted local work** on top of the
last-shipped commit (`f6407f3`, "Make the saved-analysis cache global
instead of per-user") — a full search-demand keyword research pipeline
(`autocomplete.py`, `candidates.py`, `keyword_rank.py`, `keyword_pipeline.py`),
a two-phase Gemini generation flow (`llm.understand_video` runs before the
main creative call so keyword evidence can shape titles, not just be
reconciled into tags afterward), and several correctness fixes to
`limits.py`/`analytics.py` (see §9). None of it has been pushed. Check
`git status` before assuming the working tree matches what's deployed.

---

## 1. What this project is

Two-part internship deliverable:
- **Part 1**: a Streamlit app — paste a YouTube URL, get SEO tags, titles,
  description, hashtags, chapters, hook analysis, comment sentiment,
  competitor comparison, thumbnail critique, and saved history.
- **Part 2** (the primary graded objective): a real push-to-deploy pipeline.
  `git push` -> Jenkins (test, build, push image) -> Argo CD (sync to
  Kubernetes) -> live, with zero manual steps.

Both are built and were verified working end to end multiple times — see §0
for current infra status and what's uncommitted.

Full build history and reasoning lives in the plan file:
**`~/.claude/plans/project-brief-youtube-snuggly-finch.md`** — read it if you
want the *why* behind any decision below, not just the *what*.

---

## 2. Repos and URLs

| What | Where |
|---|---|
| App source | `github.com/abhishekayachit33-code/yt-seo-assistant` |
| Deploy manifests | `github.com/abhishekayachit33-code/yt-seo-assistant-deploy` |
| Local app clone | `/Users/abhishekayachit/Task3 Intern` |
| Local deploy clone | `/Users/abhishekayachit/yt-seo-assistant-deploy` |
| Docker Hub image | `docker.io/abhishekayachit/yt-seo-assistant` |
| Public app (Streamlit Cloud) | `https://yt-seo-assistant-yva4rijzhtdrpiuqx5ena5.streamlit.app/` |
| Public app's database | Neon (serverless Postgres) |
| Local cluster app | `http://localhost:8501` (needs `kubectl port-forward`, see §4) |
| Jenkins | `http://localhost:8080` |
| Argo CD | `https://localhost:8090` (needs port-forward, self-signed cert) |

**Two entirely separate deployments exist** — don't confuse them:
1. **Local Minikube** — the actual graded pipeline (Jenkins -> Docker Hub ->
   Argo CD -> Kubernetes), backed by an in-cluster Postgres.
2. **Streamlit Community Cloud** — a public link, added afterward only so
   there's a URL to hand people. Auto-redeploys from the same GitHub repo via
   Streamlit's *own* built-in CI, has nothing to do with Jenkins/Argo CD.
   Backed by Neon, not the cluster's Postgres.

Pushing to `main` on the app repo updates **both**, independently, through
two unrelated mechanisms.

---

## 3. Architecture

```
git push (app repo)
  -> GitHub webhook -> ngrok tunnel -> Jenkins (local, port 8080)
       -> pytest (238 tests, must pass)
       -> docker build, tag :<short-sha>
       -> docker push to Docker Hub
       -> clone deploy repo, rewrite image tag in deployment.yaml, commit, push
  -> Argo CD (polls deploy repo every ~3 min) detects the new commit
       -> syncs Minikube -> old pod terminates, new pod running

(separately, same app repo push)
  -> Streamlit Community Cloud's own auto-redeploy -> public URL updates
```

In-cluster: two Deployments (`yt-seo-assistant`, `postgres`) in namespace
`yt-seo`, one Service each, one Secret (`yt-seo-secrets`, hand-created,
deliberately **not** in Git), one PVC for Postgres.

---

## 4. Resuming local work — exact commands

Everything below assumes Docker Desktop is running first (`open -a Docker`,
wait for `docker info` to succeed).

```bash
# Cluster
minikube status                    # if stopped: minikube start
kubectl get pods -n yt-seo -n argocd

# Reach the app in the cluster
kubectl port-forward -n yt-seo svc/yt-seo-assistant 8501:8501 &

# Reach Argo CD UI
kubectl port-forward -n argocd svc/argocd-server 8090:443 &
# admin password:
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d

# Reach Postgres directly (port 5432 is usually taken locally by a
# pre-existing system PostgreSQL 18 install unrelated to this project --
# use 15432 to avoid the conflict, this bit everyone all session)
kubectl port-forward -n yt-seo svc/postgres 15432:5432 &

# Jenkins + ngrok -- see §0, both currently down
```

Local Python dev:
```bash
cd "/Users/abhishekayachit/Task3 Intern"
source .venv/bin/activate
pytest -q                          # 238 tests, must be green before any push
streamlit run app.py               # local run against whatever DATABASE_URL is in .env
```

Local full-stack test (app + its own Postgres, not the cluster's):
```bash
docker compose up --build          # docker-compose.yml, throwaway ytseo/ytseo creds
docker compose down
```

---

## 5. Gotchas discovered this session — read before debugging blind

- **Local port 5432 is not free.** A real standalone PostgreSQL 18
  (`/Library/PostgreSQL/18`) runs on this Mac independent of everything here.
  Always use `15432` for cluster/Neon port-forwards, or you'll get a cryptic
  "address already in use" and waste time on it.
- **Jenkins must run as a foreground `java -jar` process, not
  `brew services start jenkins-lts`.** The brew service launchd path hung on
  first boot for unclear reasons; the direct command in §0 works reliably.
- **`kubectl port-forward` dies silently and often**, especially after the
  Mac sleeps. If `curl localhost:8501` (or 8090, or 15432) refuses, that's
  why — just re-run the port-forward command, nothing else is wrong.
- **Docker Desktop going idle takes Minikube down with it.** If `kubectl`
  commands start failing with connection-refused, check `docker info` first,
  then `minikube status`. `open -a Docker` restarts the daemon; Minikube
  needs an explicit `minikube start` after.
- **`gemini-2.5-flash` is dead for this project, do not use it.** Two
  independent reasons: (1) Google deprecates it 2026-08-16 on the original
  key; (2) it returns `404 NOT_FOUND — no longer available to new users` on
  any newer Google account/key. The whole app uses **`gemini-flash-latest`**
  (one constant, `llm.py:MODEL`) specifically to dodge both problems going
  forward — don't hardcode a dated model name again.
- **Gemini free tier is 20 requests/day per key, scoped per model.** A single
  video analysis costs 2-4 requests (see the cost table in the plan file,
  §"Cost per analysis"). Two keys are wired via `gemini_client.py`'s
  fallback, retrying on `429` (quota) and `503` (transient overload) —
  confirm both keys are genuinely on separate Google Cloud projects, or the
  fallback does nothing (same-project keys share one quota pool).
- **`@st.cache_resource` on a DB connection persists across Streamlit Cloud
  redeploys if the host does a script-level reload instead of a full process
  restart.** This caused a real production crash (`0d04d77`) — a schema
  migration silently never ran because the cached connection predated it.
  Pattern now in `db.py`: `get_connection()` only opens the connection
  (cacheable); `ensure_schema()` is separate, uncached, and must be called
  on every script run regardless of connection reuse. Follow this pattern
  for any future schema change — do not put migration SQL inside a function
  wrapped in `@st.cache_resource`.
- **Streamlit TOML secrets need actual quotes.** `KEY = "value"`, not
  `.env`-style `KEY=value` — the Community Cloud secrets box rejects the
  latter.
- **Postgres connection strings in TOML need quotes too** — same rule.

---

## 6. Credentials inventory (names only — check `.env` / cluster Secret / Neon dashboard / Streamlit secrets for values)

| Key | Used by | Lives in |
|---|---|---|
| `YOUTUBE_API_KEY` | `youtube.py`, `comments.py`, `competitors.py` | local `.env`, cluster Secret, Streamlit secrets |
| `GEMINI_API_KEY` | `llm.py`, `comments.py`, `thumbnail.py` (via `gemini_client.py`) | same three places |
| `GEMINI_API_KEY_2` | same, fallback key | same three places — **confirm separate GCP project from key 1** |
| `DATABASE_URL` | `db.py` | cluster Secret (points at in-cluster `postgres` Service), Streamlit secrets (points at Neon) — **two different values for two different databases, do not mix up** |
| `POSTGRES_PASSWORD` | `postgres-deployment.yaml` (cluster only) | cluster Secret only, generated random, not used by the app directly |

Cluster Secret name: `yt-seo-secrets`, namespace `yt-seo`, created by hand
(`kubectl create secret generic ...`), **never in Git on purpose**. If you
need to add/rotate a key: fetch existing values first, reconstruct the full
set, reapply, then `kubectl rollout restart deployment yt-seo-assistant -n yt-seo`
— Kubernetes does not hot-reload Secret changes into a running pod.

Jenkins credentials (in Jenkins' own credential store, not a file):
`dockerhub-creds` (Docker Hub access token), `github-deploy-token` (GitHub
PAT, `repo` scope, used to push into the deploy repo).

---

## 7. File map (app repo root)

| File | Role |
|---|---|
| `app.py` | Streamlit UI, wires every module together, sidebar/history |
| `llm.py` | `understand_video` (phase 1, cheap, just content_summary) + `generate_seo` (phase 2, the full call — schema, 35-tag/chapter enforcement + repair). `PROMPT_VERSION` bump required on any prompt/schema edit |
| `gemini_client.py` | Shared multi-key fallback (429/503 retry) used by every Gemini call site |
| `youtube.py` | URL parsing, video metadata fetch (YouTube Data API) |
| `transcript.py` | Transcript fetch, degrades to `None` gracefully |
| `comments.py` | Comment fetch (YouTube API) + sentiment summary (Gemini) |
| `competitors.py` | Opt-in competitor search, YouTube API only, no Gemini |
| `thumbnail.py` | Thumbnail fetch + vision critique (Gemini), for an existing video's real thumbnail |
| `thumbnail_gen.py` | Planning-mode thumbnail generation (Gemini prompt-writing + Hugging Face stable-diffusion-3.5-medium via the Replicate provider) |
| `autocomplete.py` | Demand-side evidence: YouTube's unofficial search-suggest endpoint, seed expansion, parallel fetch |
| `candidates.py` | Merges supply/demand/competitor evidence lanes, cheap filter, hand-rolled TF-IDF relevance cut |
| `keyword_rank.py` | Normalized scoring features (specificity, coverage, autocomplete strength, consensus-gated competitor signal), `RELEVANCE_FLOOR` hard cutoff, primary/secondary/long-tail strategy split |
| `keyword_pipeline.py` | Orchestrates the above end to end; entity-based seed extraction |
| `cache_key.py` | `compute_fingerprint` — what `get_cached_analysis` matches on, ties in `llm.PROMPT_VERSION` |
| `limits.py` | Real YouTube hard limits (`TITLE_MAX`/`TAGS_MAX`/etc.) AND this app's own recommendations (tag count, hashtag range) — the docstring on `compute_health_score` explains which rules are which; don't treat every rule as a YouTube fact |
| `db.py` | Postgres: connection, schema, save/list/get. History (`list_recent`/`get_analysis`) is per-user; the analysis cache (`get_cached_analysis`) is deliberately global, not scoped by user |
| `Dockerfile` | Non-root, single-stage with cache-ordered layers (`requirements.txt` copied and installed before the rest of the code, so a code-only change doesn't invalidate the pip-install layer) — NOT a real multi-stage build, despite what this doc used to say |
| `Jenkinsfile` | 5-stage pipeline: checkout, test, build, push, update-manifests |
| `docker-compose.yml` | Local app + throwaway Postgres for testing DB wiring cheaply |
| `tests/` | 238 tests across 19 files — see `ls tests/*.py` for the current list, this doc will drift again |
| `conftest.py` | Empty on purpose — anchors pytest's rootdir so flat modules import from `tests/` |

Deploy repo (`yt-seo-assistant-deploy`):
```
manifests/
  namespace.yaml, deployment.yaml, service.yaml       (app)
  postgres-pvc.yaml, postgres-deployment.yaml, postgres-service.yaml
argocd/
  application.yaml    (applied by hand once, not managed by Argo itself)
```

---

## 8. Feature -> API mapping (who actually does what)

| Feature | Gemini? | YouTube API? | Neither |
|---|---|---|---|
| Tags, titles, description, hashtags, chapters, hook, suggestions | Yes (**two** calls: `understand_video` phase 1, then `generate_seo` phase 2 — not one, since keyword evidence needs to exist before the second call) | | |
| Keyword research (primary/secondary/long-tail strategy) | Yes (one call, classification only — ranking is pure Python in `keyword_rank.py`) | Indirectly, via `autocomplete.py`'s unofficial suggest endpoint, not the official Data API | TF-IDF relevance scoring, all scoring/ranking arithmetic |
| Comment sentiment | Yes (summary only) | Yes (fetch text) | |
| Competitor comparison | **No** | Yes | |
| Thumbnail critique | Yes (vision) | Yes (fetch URL only) | |
| Thumbnail generation (planning mode) | Yes (prompt-writing + the vision critique afterward) | | Hugging Face (stable-diffusion-3.5-medium, via Replicate provider — needs real billing, see `.env`'s `HUGGINGFACE_API_KEY`) |
| Transcript | | | `youtube-transcript-api`, not an official API |
| Limit checker | | | pure Python |
| Before/after tag diff | | | pure Python |
| History | | | Postgres, per-user |
| Analysis cache | | | Postgres, global (NOT per-user — any user's prior identical-input run serves everyone) |

---

## 9. Known deviations from the original brief

- **Host is local Minikube, not GCP** (the brief's stated target). GCP's
  India signup demanded an unclear ~₹1000 pre-payment; AWS then gated every
  useful instance type behind a Paid Plan requiring a card. Architecturally
  identical either way — same Docker, same manifests, same Jenkins, same
  Argo CD. **Disclose this explicitly to whoever grades it** rather than
  letting it be discovered.
- **LLM is Gemini, not the originally-planned Groq.** Groq deprecated its
  model with a hard shutdown date mid-project.
- Public reachability is solved via a *separate* Streamlit Community Cloud
  deploy, not by exposing the cluster — the cluster was never meant to be
  publicly reachable (unauthenticated app sitting on live API keys).

---

## 10. Quick health check (run this after resuming, before doing anything else)

```bash
minikube status
kubectl get pods -n yt-seo -n argocd
kubectl get application yt-seo -n argocd -o custom-columns='SYNC:.status.sync.status,HEALTH:.status.health.status,REV:.status.sync.revision'
cd "/Users/abhishekayachit/Task3 Intern" && git log --oneline -1
cd /Users/abhishekayachit/yt-seo-assistant-deploy && git pull -q && grep image manifests/deployment.yaml
curl -s -o /dev/null -w "jenkins: %{http_code}\n" http://localhost:8080
curl -s -o /dev/null -w "ngrok: %{http_code}\n" http://localhost:4040
```

If the deploy repo's image tag doesn't match the app repo's latest commit
short-sha, the pipeline is behind — check §0.

---

## 11. Memory files from this session (auto-memory, cross-session)

Location: `~/.claude/projects/-Users-abhishekayachit-Task3-Intern/memory/`

- `feedback_trust_confirmations.md` — user doesn't want completion claims
  re-verified, except when security-relevant or a real reason to doubt
- `project_infra_host_aws.md` — **now stale**, says AWS; actual final host
  is local Minikube (AWS was rejected too, after GCP, before landing local).
  Worth correcting or removing next time it's touched.
