# YouTube SEO Assistant — Project Brief

## What this is

An internship project with two graded parts:

**Part 1** — a Streamlit web app. User pastes a YouTube URL, the app fetches
that video's metadata, transcript, and comments, researches what people
actually search for, and returns a keyword strategy plus SEO tags,
alternative titles, an optimized description, hashtags, chapter timestamps,
a hook-quality analysis, comment sentiment, an opt-in competitor comparison,
a thumbnail critique, and a saved history of past analyses. A second mode
plans a video that has not been recorded yet.

**Part 2** (the primary graded objective) — a real push-to-deploy pipeline.
A single `git push` results in the change being tested, containerized, and
running in a Kubernetes cluster with no manual step in between.

## How the analysis actually works

Worth stating plainly, because "sends it to an LLM and shows the answer" is
what this started as and is no longer accurate:

1. **Understand** (Gemini call 1, small) — produces a working summary of the
   video plus a `target_audience` naming the viewer's *decision stage*, not
   just demographics.
2. **Research demand** — three evidence lanes merge into a candidate pool:
   transcript n-grams (what the video says), YouTube's search-suggest
   endpoint (what people type), and competitor titles/tags (what already
   ranks). Several hundred candidates get cut cheaply by TF-IDF relevance,
   then one Gemini call classifies the survivors for intent and topical fit.
3. **Rank** — pure Python, deliberately not the model. Normalised features
   (relevance, specificity, coverage, autocomplete position, intent,
   consensus-gated competitor signal) produce a primary/secondary/long-tail
   strategy where every keyword carries stated evidence. Kept deterministic
   so it is testable and tunable without spending an API call.
4. **Generate** (Gemini call 2) — titles and description are written *with*
   the demand evidence and audience in hand, rather than written first and
   reconciled afterward.

Hard constraints (YouTube's real 500-character tag cap) are enforced in
Python regardless of what the model returns, because in production it once
returned 991 characters against that limit.

Planning mode runs the same pipeline with one deliberate inversion: for an
unrecorded video, "your draft does not cover this in-demand phrase" is an
opportunity to write about rather than a warning, surfaced as a content-gap
list. Input too thin to research from is refused outright rather than
answered with confident guesswork.

## Current status: both parts are built and working

Not a prototype — this has been built, tested, and re-verified live multiple
times, including finding and fixing real bugs under actual production
conditions (not just passing unit tests). 262 automated tests gate every
deploy; the pipeline refuses to build if any fail.

## Tech stack

- **App**: Python, Streamlit
- **LLM**: Google Gemini (`gemini-flash-latest`) — chosen specifically because
  one model handles both text generation and image (thumbnail) analysis.
  2 calls per analysis (understand, then generate), plus one for keyword
  classification and one more only if the output violates a hard constraint
  and needs repair
- **Data source**: YouTube Data API (metadata, comments, competitor search),
  `youtube-transcript-api` (transcript, unofficial library), and Google's
  undocumented search-suggest endpoint for demand data — the last of these
  has no SLA, so every lane degrades independently rather than failing the
  analysis
- **Database**: Postgres. Saved history is per-user; the analysis cache is
  global and keyed on a content fingerprint, so two users analysing the same
  unchanged video share one result instead of spending two LLM calls
- **Container**: Docker
- **CI**: Jenkins (test -> build -> push image -> update deploy manifests)
- **CD**: Argo CD (GitOps — watches a Git repo, syncs Kubernetes to match it)
- **Cluster**: Kubernetes (Minikube, running locally rather than on a paid
  cloud VM — GCP and AWS both hit payment/billing walls during setup)
- **Registry**: Docker Hub
- **Public access**: a separate deploy on Streamlit Community Cloud, backed
  by Neon (serverless Postgres) — independent of the Kubernetes pipeline,
  added only so there's a URL to hand people

## Architecture (Part 2, the pipeline)

Two Git repos:
- App source repo — the Python code, Dockerfile, Jenkins pipeline definition
- Deploy repo — only Kubernetes YAML manifests (Deployment, Service, PVC)

Flow: pushing to the app repo triggers a GitHub webhook, which starts a
Jenkins job. Jenkins runs the test suite, builds a Docker image tagged with
the commit hash, pushes it to Docker Hub, then edits the deploy repo's
manifest to point at that new image tag and pushes that commit. Argo CD is
separately watching the deploy repo; it notices the change and applies it to
the Kubernetes cluster, replacing the running pod with one on the new image.
No human touches the cluster at any point in this chain.

## What's been verified, not just built

- The full pipeline was proven with a real webhook-triggered push (not a
  manual "Build Now" click) landing a change in the running cluster in under
  5 minutes.
- Argo CD's self-healing was proven by manually deleting the running
  Kubernetes Deployment and watching it get recreated automatically.
- Postgres persistence was proven by deleting the database pod entirely and
  confirming saved data survived on its persistent volume.
- Multiple real, non-obvious bugs were found and fixed by testing under
  actual conditions rather than trusting green checkmarks — e.g. an LLM
  model that returned different errors depending on which Google account
  the API key belonged to, and a database connection caching bug that only
  showed up on the public cloud deploy's specific redeploy behavior, not
  locally or in the Kubernetes cluster.
- The keyword pipeline was validated against a real channel's YouTube Studio
  analytics rather than assumed correct. That comparison caught a genuine
  ranking bug (a barely-mentioned phrase outranking the video's actual
  subject) and, more usefully, *stopped* a planned fix: a diagnostic across
  17 videos showed the obvious remedy would have rejected four good keyword
  picks for every real bug it caught, because the coverage metric it would
  have gated on fails on paraphrase. The fix was dropped on the evidence.
- Several confidently-worded claims in the code turned out to be wrong when
  checked against reality — the app scored hashtags against a 10-15 target
  when actual best practice is 3-5, and described its own invented uplift
  bands as "published". Both corrected; the underlying lesson (this app's
  opinions were formatted identically to YouTube's rules) is now called out
  explicitly in `limits.py`.

## Known, deliberate deviations from the original brief

- Hosting is local (Minikube on a laptop), not a cloud VM as originally
  specified — both GCP and AWS required payment commitments that weren't
  available; architecturally this is a drop-in swap, same Docker/Kubernetes/
  Jenkins/Argo CD regardless of host.
- The original plan specified a different LLM provider (Groq); switched to
  Gemini after Groq deprecated the model this project depended on, and
  because Gemini uniquely allows one model/client to handle both the text
  generation and the thumbnail vision feature.

## What's not built

- No real user authentication — history separation between users is done
  with a plain typed name, not a login system, by deliberate scope choice.
  Anyone who types another user's exact name sees their history.
- No CI/CD for the Kubernetes manifests' own correctness beyond Argo CD's
  sync — no manifest linting stage in the pipeline.
- The public Streamlit Cloud deploy's database (Neon) is separate from the
  Kubernetes cluster's database — they do not share history.
- **No real search-volume data.** YouTube's API does not expose it, and every
  free source is dead (Google Trends' unofficial library was archived in
  2025; the official API is allowlisted). Demand is therefore represented as
  *autocomplete rank position* — an ordinal strength signal — and is named
  that way in the code rather than dressed up as a volume number the app
  cannot actually know.
- **No causal validation of the keyword advice.** The comparison against real
  channel analytics was retrospective: those videos were never titled using
  this tool, so it can surface bugs but cannot prove the advice works. Real
  validation would mean using the tool on new videos and checking their
  performance weeks later.
- Thumbnail generation (planning mode) is code-complete and tested but
  requires paid Hugging Face inference credits; it returns HTTP 402 until
  billing is added.
- The keyword pipeline assumes a long-form, search-discoverable video.
  Checked against a Shorts channel where 92% of views came from the Shorts
  feed and only 2.2% from search, most of this app's assumptions do not
  apply — it targets a specific kind of channel and does not pretend
  otherwise.
