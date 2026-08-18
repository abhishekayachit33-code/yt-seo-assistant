# Handoff — YouTube SEO Assistant + GitOps Pipeline

Last updated: 2026-08-18. Read this top-to-bottom before touching anything —
the "Act on this first" section is not optional.

---

## 0. Act on this first

**Minikube/Docker/Jenkins/ngrok are all down right now** (confirmed live
while updating this doc — Docker daemon socket gone, `kubectl` refuses to
connect, Jenkins 000, ngrok's local API unreachable). Same recurring failure
mode as always: none of these auto-start, and they go down every time this
laptop sleeps or reboots. To recover, in order:
`open -a Docker` and wait for `docker info` to succeed, `minikube start`,
start Jenkins as a foreground process — **use the Homebrew JDK, not the
system `java` stub**:
```bash
nohup /opt/homebrew/opt/openjdk@21/bin/java -jar \
  /opt/homebrew/Cellar/jenkins-lts/2.568.1/libexec/jenkins.war --httpPort=8080 &
```
(`/usr/bin/java` on this Mac has no real JDK behind it and fails silently —
see §5.) Then start `ngrok http 8080`, then check whether the GitHub webhook
URL still matches the ngrok tunnel (it rotates on every restart on the free
tier) — `gh api repos/abhishekayachit33-code/yt-seo-assistant/hooks` shows
the current registered URL, `curl localhost:4040/api/tunnels` shows the
current one.

**There is substantial uncommitted local work, larger than last time.**
Last pushed commit is `a98cd43` ("Retry Gemini calls with backoff before
switching keys, log every attempt"). On top of that, uncommitted:
- A full **DeepSeek integration** (`deepseek_client.py`, new) — DeepSeek is
  now tried BEFORE Gemini on every text-generation call, not just a
  fallback. See §8.
- **Two transcript fixes** in `transcript.py` and a new Gemini-video-watch
  fallback in `llm.py` (`generate_transcript_from_video`). See §9.
- **`llm.py`'s `MODEL` constant is currently `"gemini-2.5-flash"`**, changed
  from `"gemini-flash-latest"` as a live experiment (§9 explains why, and
  that this directly contradicts an old warning further down this doc that
  was never removed — resolve that contradiction before shipping this).

None of it has been pushed. Check `git status` before assuming the working
tree matches what's deployed. Run `pytest -q` (280 tests as of this writing)
before pushing anything — it's green on the current working tree.

---

## 1. What this project is

Two-part internship deliverable:
- **Part 1**: a Streamlit app — paste a YouTube URL, get SEO tags, titles,
  description, hashtags, chapters, hook analysis, comment sentiment,
  competitor comparison, thumbnail critique, keyword research, and saved
  history. Also a "Plan a new video" mode that does the same from a script
  alone, before a video exists.
- **Part 2** (the primary graded objective): a real push-to-deploy pipeline.
  `git push` -> Jenkins (test, build, push image) -> Argo CD (sync to
  Kubernetes) -> live, with zero manual steps. Verified working end to end
  multiple times, including as recently as this session.

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
   Backed by Neon, not the cluster's Postgres. **Does not have `DEEPSEEK_API_KEY`
   configured in its secrets yet** — will silently fall back to Gemini-only
   until that's added there too.

Pushing to `main` on the app repo updates **both**, independently, through
two unrelated mechanisms.

---

## 3. Architecture

```
git push (app repo)
  -> GitHub webhook -> ngrok tunnel -> Jenkins (local, port 8080)
       -> pytest (280 tests, must pass)
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
kubectl get pods -n yt-seo
kubectl get pods -n argocd

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

# Jenkins -- foreground, correct JDK (see §0 and §5)
nohup /opt/homebrew/opt/openjdk@21/bin/java -jar \
  /opt/homebrew/Cellar/jenkins-lts/2.568.1/libexec/jenkins.war --httpPort=8080 &

# ngrok -- separate terminal, needs the user to run it (auto-mode blocks
# starting it directly since it exposes a local port publicly)
ngrok http 8080
```

Local Python dev:
```bash
cd "/Users/abhishekayachit/Task3 Intern"
source .venv/bin/activate
pytest -q                          # 280 tests, must be green before any push
streamlit run app.py               # local run against whatever DATABASE_URL is in .env
```

Local full-stack test (app + its own Postgres, not the cluster's):
```bash
docker compose up --build          # docker-compose.yml, throwaway ytseo/ytseo creds
docker compose down
```

---

## 5. Gotchas discovered — read before debugging blind

- **`/usr/bin/java` on this Mac is a stub with no real JDK behind it** —
  running Jenkins with plain `java -jar jenkins.war` fails with "Unable to
  locate a Java Runtime" even though `which java` succeeds. The real JDKs
  are Homebrew-installed but not symlinked system-wide. Always launch
  Jenkins with the explicit path: `/opt/homebrew/opt/openjdk@21/bin/java`
  (or `openjdk@17`, both installed).
- **Only one `ngrok` agent session works at a time** on the free tier. If a
  previous `ngrok` process is left running (even stopped/suspended via job
  control — check `lsof -i :4040`), a newly started one will bind to a
  random different port or silently fail to serve its local API on 4040.
  Kill the stale process first, then start fresh.
- **Local port 5432 is not free.** A real standalone PostgreSQL 18
  (`/Library/PostgreSQL/18`) runs on this Mac independent of everything here.
  Always use `15432` for cluster/Neon port-forwards, or you'll get a cryptic
  "address already in use" and waste time on it.
- **`kubectl port-forward` dies silently and often**, especially after the
  Mac sleeps. If `curl localhost:8501` (or 8090, or 15432) refuses, that's
  why — just re-run the port-forward command, nothing else is wrong.
- **Docker Desktop going idle takes Minikube down with it**, and takes
  Jenkins/ngrok's usefulness down too since they're separate host processes
  that don't restart themselves. If `kubectl` commands start failing with
  connection-refused, check `docker info` first, then `minikube status`.
  `open -a Docker` restarts the daemon; Minikube needs an explicit
  `minikube start` after. This is the single most common time-waster across
  every session on this project — always run the §10 health check first.
- **Gemini free tier is 20 requests/day, per key, per model.** This bit hard
  this session: heavy live testing exhausted both `GEMINI_API_KEY` and
  `GEMINI_API_KEY_2` on `gemini-flash-latest` (which currently resolves to
  `gemini-3.7-flash` internally — that's the real quota bucket name that
  shows up in error messages, not the alias). Confirmed live: the quota is
  bucketed **per exact model name**, not shared — `gemini-2.5-flash` still
  had a full 20/20 available on a key that was fully exhausted on
  `gemini-flash-latest` at the same moment. Two keys are wired via
  `gemini_client.py`'s fallback with retry+backoff (see below) — confirm
  both keys are genuinely on separate Google Cloud projects, or quota
  exhaustion hits both simultaneously (as it did this session).
- **`gemini-2.5-flash` status is unresolved and contradictory.** An older
  version of this doc said it was dead (deprecated 2026-08-16, `404`s on
  newer accounts) and told future sessions never to hardcode it again.
  Live-tested this session anyway (separate quota bucket, see above) and it
  **worked cleanly**, both a raw smoke test and a real `understand_video()`
  call through the actual pipeline. `llm.py:MODEL` is currently set to it as
  an uncommitted experiment (§0). Before shipping this: figure out why the
  old warning doesn't match observed behavior — different account tier?
  deprecation not actually enforced yet? — rather than trusting either the
  old note or the one successful test blindly.
- **429 vs 503 look similar but mean different things, and retries can make
  429 worse.** 503 ("high demand") is transient Google-side overload, worth
  a short backoff retry. 429 ("quota exceeded") on the free tier's *daily*
  quota does not clear in seconds — retrying it with backoff just burns time
  and, worse, each retry still counts as a request, so it can push a
  borderline-exhausted key over the edge faster. `gemini_client.py` retries
  both the same way (3x, 1s/2s/4s backoff) — this was seen live turning a
  key from 503 into 429 mid-run. A cleaner fix (skip straight to the next
  key on 429, only backoff-retry on 503) was identified but **not yet
  implemented** — worth doing.
- **Every Gemini/DeepSeek call attempt is now logged** — key/provider
  position, attempt number, status code — specifically so this kind of
  quota/overload confusion is diagnosable from logs instead of guesswork.
  Check terminal output before assuming which failure mode is happening.
- **`youtube_transcript_api`'s `.fetch()` defaults to English only.** Fixed
  this session (§9) — used to silently return `None` for a video whose only
  captions were in another language. Now falls back to any available
  transcript (manually-created still preferred over auto-generated) when
  English isn't found.
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
  latter. Same for Postgres connection strings.

---

## 6. Credentials inventory (names only — check `.env` / cluster Secret / Neon dashboard / Streamlit secrets for values)

| Key | Used by | Lives in |
|---|---|---|
| `YOUTUBE_API_KEY` | `youtube.py`, `comments.py`, `competitors.py` | local `.env`, cluster Secret, Streamlit secrets |
| `GEMINI_API_KEY` | `llm.py`, `comments.py`, `thumbnail.py` (via `gemini_client.py`) | same three places |
| `GEMINI_API_KEY_2` | same, fallback key | same three places — **confirm separate GCP project from key 1** (this session's quota exhaustion hit both keys together, consistent with them sharing a project, though never explicitly confirmed) |
| `DEEPSEEK_API_KEY` | `llm.py` (text generation only, via `deepseek_client.py`) | **local `.env` only** — not yet added to cluster Secret or Streamlit secrets. Paid, tried BEFORE Gemini on every text call (`understand_video`/`generate_seo`/`judge_keywords`); Gemini is now the fallback, not the primary, for text. Never used for vision — DeepSeek has no vision/audio model, confirmed against their own API docs |
| `DATABASE_URL` | `db.py` | cluster Secret (points at in-cluster `postgres` Service), Streamlit secrets (points at Neon) — **two different values for two different databases, do not mix up** |
| `POSTGRES_PASSWORD` | `postgres-deployment.yaml` (cluster only) | cluster Secret only, generated random, not used by the app directly |

Cluster Secret name: `yt-seo-secrets`, namespace `yt-seo`, created by hand
(`kubectl create secret generic ...`), **never in Git on purpose**. If you
need to add/rotate a key (e.g. finally add `DEEPSEEK_API_KEY` there): fetch
existing values first, reconstruct the full set, reapply, then
`kubectl rollout restart deployment yt-seo-assistant -n yt-seo`
— Kubernetes does not hot-reload Secret changes into a running pod.

Jenkins credentials (in Jenkins' own credential store, not a file):
`dockerhub-creds` (Docker Hub access token), `github-deploy-token` (GitHub
PAT, `repo` scope, used to push into the deploy repo).

---

## 7. File map (app repo root)

| File | Role |
|---|---|
| `app.py` | Streamlit UI, wires every module together, sidebar/history |
| `llm.py` | `understand_video` (phase 1, cheap, content_summary+audience) + `generate_seo` (phase 2, the full call). New: `generate_transcript_from_video` (Gemini-only video-watch fallback), `_generate_json`/`_ProviderResponse` (DeepSeek-first provider router). `PROMPT_VERSION` bump required on any prompt/schema edit |
| `gemini_client.py` | Multi-key Gemini fallback with retry+backoff (429/503) and per-attempt logging |
| `deepseek_client.py` | **New.** DeepSeek REST client (OpenAI-compatible endpoint), same retry+backoff/logging shape as `gemini_client.py` |
| `youtube.py` | URL parsing, video metadata fetch (YouTube Data API) |
| `transcript.py` | Transcript fetch. Now tries English first, falls back to any available language (manual-preferred) instead of silently giving up. Degrades to `None` if no captions exist in any language |
| `comments.py` | Comment fetch (YouTube API) + sentiment summary (Gemini — **not yet routed through DeepSeek**, only `llm.py`'s three functions are) |
| `competitors.py` | Opt-in competitor search, YouTube API only, no Gemini |
| `thumbnail.py` | Thumbnail fetch + vision critique (Gemini only — DeepSeek has no vision capability) |
| `thumbnail_gen.py` | Planning-mode thumbnail generation (Gemini prompt-writing + Hugging Face stable-diffusion-3.5-medium via Replicate). **Not yet routed through DeepSeek** even though its prompt-writing step is text-only and could be |
| `autocomplete.py` | Demand-side evidence: YouTube's unofficial search-suggest endpoint, seed expansion, parallel fetch |
| `candidates.py` | Merges supply/demand/competitor evidence lanes, cheap filter, hand-rolled TF-IDF relevance cut |
| `keyword_rank.py` | Normalized scoring features, `RELEVANCE_FLOOR` hard cutoff, primary/secondary/long-tail strategy split |
| `keyword_pipeline.py` | Orchestrates the above end to end; entity-based seed extraction. `run()` now also accepts `deepseek_api_key`, threaded into `judge_keywords` |
| `plan_input.py` | `is_plan_input_sufficient(script)` — planning mode's hard input gate. Simplified this session: script is now the sole requirement, title/description/tags are pure enrichment (was previously "any one of title/description/script/tags") |
| `cache_key.py` | `compute_fingerprint` — what `get_cached_analysis` matches on, ties in `llm.PROMPT_VERSION` |
| `limits.py` | Real YouTube hard limits AND this app's own recommendations — the docstring on `compute_health_score` explains which rules are which |
| `db.py` | Postgres: connection, schema, save/list/get. History is per-user; the analysis cache is deliberately global |
| `Dockerfile` | Non-root, single-stage with cache-ordered layers |
| `Jenkinsfile` | 5-stage pipeline: checkout, test, build, push, update-manifests |
| `docker-compose.yml` | Local app + throwaway Postgres for testing DB wiring cheaply |
| `tests/` | 280 tests across 22+ files as of this session (was 238 at last doc update) |
| `conftest.py` | Empty on purpose — anchors pytest's rootdir |

Deploy repo (`yt-seo-assistant-deploy`):
```
manifests/
  namespace.yaml, deployment.yaml, service.yaml       (app)
  postgres-pvc.yaml, postgres-deployment.yaml, postgres-service.yaml
argocd/
  application.yaml    (applied by hand once, not managed by Argo itself)
```

---

## 8. DeepSeek integration (new this session, uncommitted)

**What changed**: DeepSeek is now tried **before** Gemini on every
text-generation call — not a fallback-of-last-resort, the primary path.
Rationale: it's paid, has no free-tier daily-quota/overload problem, and
this session repeatedly hit Gemini's 20/day wall during normal testing.

**Model**: `deepseek-v4-flash` (`llm.py:DEEPSEEK_MODEL`) — confirmed live
against the account's actual `/models` endpoint; the older `deepseek-chat`
alias still worked in a smoke test but no longer appears in the models list,
so don't rely on it going forward.

**How the routing works** (`llm.py:_generate_json`): every one of
`understand_video`, `judge_keywords`, `repair_output`, `generate_seo` now
takes an optional `deepseek_api_key` param (default `None`, so nothing
changes for any caller that doesn't pass it — this is why none of the ~20
existing Gemini-mock tests needed changes). If a key is supplied, DeepSeek
is tried first; on ANY DeepSeek failure it falls straight through to the
existing Gemini multi-key chain, unchanged. `app.py` reads
`DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")` and threads it into all 8
call sites (both analyze and planning paths, including the title-variant
loop and `keyword_pipeline.run`).

**Structural limits, not implementation gaps**:
- **DeepSeek is text-only.** Confirmed against their own API docs — no
  audio, no video, no image input anywhere in their API surface. Vision
  (thumbnail critique) and the new video-watch transcript fallback (§9) are
  Gemini-only by necessity, not by choice, and always will be unless
  DeepSeek ships a vision model.
- **DeepSeek's JSON mode is not schema-enforced like Gemini's
  `response_schema`.** The schema is embedded in the prompt as guidance in
  `deepseek_client.generate_json`; DeepSeek guarantees syntactically valid
  JSON but not a specific shape. This app's existing `repair_output` pass
  (asks the model to fix constraint violations) is the safety net for this
  regardless of which provider answered — not a new risk, just a
  higher-probability path to it firing.

**Not yet done**:
- `DEEPSEEK_API_KEY` isn't in the cluster Secret or Streamlit Cloud secrets
  yet — only local `.env`. Both deployed environments currently fall back to
  Gemini-only until this is added.
- `comments.py` and `thumbnail_gen.py`'s text-only prompt-writing step
  aren't routed through DeepSeek — only `llm.py`'s three functions are.
  Scoped that way deliberately this session; revisit if it's worth widening.
- Retries burn real spend on DeepSeek differently than on free-tier Gemini
  — unconfirmed whether DeepSeek bills/counts a 429/5xx retry attempt the
  same as Gemini's free tier does (where it just costs time). Check their
  dashboard's usage page if request counts look surprising.

---

## 9. Transcript reliability work (new this session, uncommitted)

Three separate, real problems addressed:

1. **English-only default bug, fixed.** `transcript.py`'s `fetch()` call
   defaulted to `languages=('en',)` — any video whose only captions were in
   another language silently returned `None`. Now tries English first
   (unchanged fast path), falls back to any available transcript on
   `NoTranscriptFound` (manually-created still preferred over
   auto-generated — same priority `find_transcript` itself uses, just not
   restricted to a language allowlist). Verified live against a
   Korean-only-captioned video.

2. **No-captions-at-all fallback, added.** When a video has no transcript in
   any language, `llm.generate_transcript_from_video(api_keys, video_url)`
   asks Gemini to watch the video directly (`file_data`/`file_uri`, a real
   documented Gemini capability, confirmed live) and produce the spoken
   content as flat prose. **Deliberately no fake timestamps** — Gemini's
   self-reported timing from watching a video is its own estimate, not
   measured caption data, and there's no way to verify its precision from
   here. `app.py`'s analyze path calls this when `fetch_transcript_segments`
   returns `None`; `transcript_segments` stays `None` in this case (no real
   per-line timing exists), so pacing/silent-gap/CTA features degrade
   exactly like any other caption-less video already does — only the flat
   transcript text and keyword supply-lane evidence gain anything.
   `generate_seo(suppress_chapters=transcript_is_generated)` — chapters are
   never built against this synthetic timing, reusing the exact pattern
   planning mode already had for "no real duration to base timestamps on."
   **Gemini-only** — DeepSeek cannot do this, see §8.

3. **Auto-generated caption quality — identified, not yet fixed.** When only
   auto-generated (ASR) captions exist (the common case for a small
   channel), there's still no quality signal surfaced anywhere — the
   library's `is_generated` flag is fetched but discarded. A misheard
   proper noun/technical term can silently corrupt keyword seed extraction
   or hook-analysis wording. Two cheap fixes identified but not built:
   surface the flag as a UI caveat, and/or let the analyze path (not just
   planning mode) accept a manual transcript override.

**Explicitly considered and rejected this session**: `yt-dlp` (download
audio) + AssemblyAI (paid ASR) as a transcript source. Technically works,
but: needs `ffmpeg` in the Docker image (not there today), a 90-minute video
would take an estimated 15-30+ minutes end-to-end (download + async
transcription polling) which doesn't fit this app's fully-synchronous
Streamlit request model at all without adding real background-job infra,
costs real money per video, and sits in a legal gray zone against YouTube's
ToS the same way the GCP->Minikube and Groq->Gemini deviations already
disclosed in §11 do. The Gemini-video-watch approach (item 2 above) gets
most of the value with none of that cost.

---

## 10. Quick health check (run this after resuming, before doing anything else)

```bash
minikube status
kubectl get pods -n yt-seo
kubectl get pods -n argocd
kubectl get application yt-seo -n argocd -o custom-columns='SYNC:.status.sync.status,HEALTH:.status.health.status,REV:.status.sync.revision'
cd "/Users/abhishekayachit/Task3 Intern" && git status && git log --oneline -1
cd /Users/abhishekayachit/yt-seo-assistant-deploy && git pull -q && grep image manifests/deployment.yaml
curl -s -o /dev/null -w "jenkins: %{http_code}\n" http://localhost:8080
curl -s http://localhost:4040/api/tunnels
gh api repos/abhishekayachit33-code/yt-seo-assistant/hooks --jq '.[].config.url'
```

If the deploy repo's image tag doesn't match the app repo's latest commit
short-sha, the pipeline is behind — check §0. If the ngrok URL doesn't match
the registered webhook URL, update the webhook (`gh api` or the GitHub
repo's Settings -> Webhooks page) before expecting pushes to trigger builds.

To check whether Gemini keys are currently quota-exhausted vs just
overloaded, there's no free way to check — any check costs a real request.
See §5's note on 429 vs 503, and check terminal logs from the last real run
before spending another request just to find out.

---

## 11. Known deviations from the original brief

- **Host is local Minikube, not GCP** (the brief's stated target). GCP's
  India signup demanded an unclear ~₹1000 pre-payment; AWS then gated every
  useful instance type behind a Paid Plan requiring a card. Architecturally
  identical either way — same Docker, same manifests, same Jenkins, same
  Argo CD. **Disclose this explicitly to whoever grades it** rather than
  letting it be discovered.
- **LLM is DeepSeek-primary with Gemini fallback, not solely Gemini** (which
  itself replaced the originally-planned Groq after Groq deprecated its
  model with a hard shutdown date mid-project). Same disclosure logic
  applies to this latest swap — it changes which provider actually wrote a
  given output, worth being upfront about if asked.
- Public reachability is solved via a *separate* Streamlit Community Cloud
  deploy, not by exposing the cluster — the cluster was never meant to be
  publicly reachable (unauthenticated app sitting on live API keys).

---

## 12. Memory files (auto-memory, cross-session)

Location: `~/.claude/projects/-Users-abhishekayachit-Task3-Intern/memory/`

- `feedback_trust_confirmations.md` — user doesn't want completion claims
  re-verified, except when security-relevant or a real reason to doubt.
- `project_infra_host_aws.md` — already correct (fixed 2026-08-05): final
  host is local Minikube, not GCP or AWS (both were rejected in turn before
  landing local). An older version of this handoff doc claimed this memory
  was still stale/wrong — that claim was itself the stale part; checked the
  memory file directly this session and it's accurate. Not the same as
  saying the *code* has no leftover GCP/AWS references — only that this
  specific memory's content is correct.
- `reference_handoff_doc.md` — points here. Still accurate.
