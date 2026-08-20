"""FastAPI backend for the React/Next.js frontend.

Phase 1 of the Streamlit -> React migration: wraps the existing,
UI-agnostic business logic (root-level keyword_pipeline.py, llm.py,
youtube.py, etc.) behind HTTP endpoints instead of an inline Streamlit
script. Business logic itself is untouched -- this file is orchestration
and auth only.

Endpoints implemented this phase: signup/login/me, history list/get,
analyze. Plan-a-new-video, thumbnail generation/critique, and export are
follow-up phases (see handoff.md) -- each is its own render_* function in
the old app.py and maps to its own endpoint the same way /analyze does.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Sibling modules (keyword_pipeline.py, llm.py, ...) live at the repo root,
# one level above this package -- add it to sys.path so `import llm` etc.
# resolve regardless of the working directory uvicorn is started from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# load_dotenv() with no path walks up from the CURRENT WORKING DIRECTORY,
# not from this file's location -- uvicorn is typically started from
# backend/, which has no .env of its own, so the repo root's .env (API
# keys, DATABASE_URL, JWT_SECRET) was silently never loaded. Same class of
# bug as an earlier one this session (a script under /private/tmp never
# finding Task3 Intern's .env). Explicit path, not cwd-dependent.
load_dotenv(os.path.join(_REPO_ROOT, ".env"))

from cache_key import compute_fingerprint
from comments import fetch_top_comments
from competitors import find_competitors
import keyword_pipeline
from keyword_rank import format_keyword_evidence, merge_into_tags
from llm import (
    VideoUnderstanding, enforce_tag_char_limit, generate_seo, generate_transcript_from_video,
    understand_video,
)
import sanitize
from thumbnail import critique_thumbnail, critique_thumbnail_bytes
from thumbnail_gen import generate_thumbnail_image, generate_thumbnail_prompts
from transcript import fetch_transcript_segments, segments_to_text
from youtube import (
    InvalidURLError, VideoMeta, VideoNotFoundError, build_planned_meta, fetch_metadata, parse_video_id,
)

from . import auth, db
from .report import build_report
from .schemas import (
    AnalyzeRequest, HistoryItem, LoginRequest, PlanRequest, SignupRequest, ThumbnailCritiqueRequest,
    ThumbnailGenerateRequest, TokenResponse, UserOut,
)

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEYS = [k for k in [GEMINI_API_KEY, os.getenv("GEMINI_API_KEY_2")] if k]
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

app = FastAPI(title="YouTube SEO Studio API")

app.add_middleware(
    CORSMiddleware,
    # Comma-separated in env so prod can list the real Next.js origin(s)
    # without a code change; defaults to the Next.js dev server only.
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer()


def get_db():
    conn = db.get_connection()
    if conn is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable")
    if not db.ensure_schema(conn):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database schema check failed")
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    conn=Depends(get_db),
) -> dict:
    payload = auth.decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get_user_by_id(conn, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


# --------------------------------------------------------------------- auth


@app.post("/auth/signup", response_model=TokenResponse)
def signup(body: SignupRequest, conn=Depends(get_db)):
    if db.get_user_by_email(conn, body.email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = db.create_user(conn, body.email, auth.hash_password(body.password), body.display_name)
    token = auth.create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token, user=UserOut(**user))


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, conn=Depends(get_db)):
    user = db.get_user_by_email(conn, body.email)
    if user is None or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    token = auth.create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=token,
        user=UserOut(id=user["id"], email=user["email"], display_name=user["display_name"]),
    )


@app.get("/auth/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    return UserOut(**user)


# ------------------------------------------------------------------ history


@app.get("/history", response_model=list[HistoryItem])
def history(search: str = "", user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return db.list_recent(conn, user["id"], search=search)


@app.get("/history/{analysis_id}")
def history_item(analysis_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    result = db.get_analysis(conn, user["id"], analysis_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return result


@app.get("/history/{analysis_id}/report")
def history_report(analysis_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    """A saved analysis rendered as the same report bundle /analyze returns,
    but DEGRADED (live=False) -- exactly what app.py did on a history click.

    Only the generated result is stored; the video's own description, tags,
    view count, transcript and competitor set are not. So everything derived
    from those (tag diff, reach projection, revenue, playbook, keyword
    strategy, pacing) is genuinely unavailable rather than recomputable, and
    is reported as absent instead of being faked from an empty VideoMeta.
    """
    row = conn.execute(
        "SELECT video_id, title, channel, analyzed_at FROM analyses WHERE id = %s AND user_id = %s",
        (analysis_id, user["id"]),
    ).fetchone()
    result = db.get_analysis(conn, user["id"], analysis_id)
    if row is None or result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")

    video_id, title, channel, analyzed_at = row
    meta = VideoMeta(
        video_id=video_id, title=title, description="", tags=[], channel_title=channel,
        thumbnail_url=(
            "" if video_id.startswith("planned-")
            else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        ),
    )
    report = build_report(
        meta, result, live=False, planning=video_id.startswith("planned-"),
        note=f"Saved {analyzed_at:%d %b %Y, %H:%M} · no API quota spent",
    )
    report["analysis_id"] = analysis_id
    return report


# ------------------------------------------------------------------ analyze


@app.post("/analyze")
def analyze(
    body: AnalyzeRequest, user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    """Mirrors app.py's `if run:` block (old Streamlit script), minus the
    st.status() progress narration -- the frontend can show its own loading
    state from the single request/response instead of a server-sent log."""
    if not YOUTUBE_API_KEY or not GEMINI_API_KEY:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Server is missing API keys")

    try:
        video_id = parse_video_id(body.url)
    except InvalidURLError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    try:
        meta = fetch_metadata(video_id, YOUTUBE_API_KEY)
    except VideoNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to fetch video metadata: {exc}")

    transcript_segments = fetch_transcript_segments(video_id)
    transcript = segments_to_text(transcript_segments) if transcript_segments else None
    transcript_is_generated = False
    if not transcript and GEMINI_API_KEYS:
        transcript = generate_transcript_from_video(GEMINI_API_KEYS, f"https://www.youtube.com/watch?v={video_id}")
        transcript_is_generated = transcript is not None

    top_comments = fetch_top_comments(video_id, YOUTUBE_API_KEY)

    competitors = []
    if body.include_competitors:
        competitors = find_competitors(meta.title, YOUTUBE_API_KEY, exclude_video_id=video_id)

    fingerprint = compute_fingerprint(meta.title, meta.description, meta.tags, transcript, top_comments)
    cached_result = db.get_cached_analysis(conn, video_id, fingerprint)

    def run_keyword_pipeline(content_summary: str, entities: list[str] | None = None):
        if not body.run_keyword_pipeline:
            return None
        try:
            return keyword_pipeline.run(
                api_keys=GEMINI_API_KEYS, content_summary=content_summary,
                title=meta.title, description=meta.description, existing_tags=meta.tags,
                transcript=transcript, transcript_segments=transcript_segments,
                competitors=competitors, deepseek_api_key=DEEPSEEK_API_KEY, llm_entities=entities,
            )
        except Exception as exc:
            logger.warning("keyword pipeline failed, continuing without it: %s", exc)
            return None

    warning = None
    analysis_id = None

    if cached_result is not None:
        result = cached_result
        keyword_result = run_keyword_pipeline(result.get("content_summary", ""))
    else:
        try:
            understanding = understand_video(
                api_keys=GEMINI_API_KEYS, title=meta.title, description=meta.description,
                existing_tags=meta.tags, transcript=transcript, comments=top_comments,
                deepseek_api_key=DEEPSEEK_API_KEY,
            )
        except Exception as exc:
            logger.warning("understand_video failed, generating without keyword evidence: %s", exc)
            understanding = VideoUnderstanding()

        keyword_result = run_keyword_pipeline(understanding.content_summary, understanding.entities)
        keyword_evidence = None
        if keyword_result is not None and not keyword_result.weak_evidence:
            keyword_evidence = format_keyword_evidence(keyword_result.strategy) or None

        try:
            result = generate_seo(
                api_keys=GEMINI_API_KEYS, title=meta.title, description=meta.description,
                existing_tags=meta.tags, transcript=transcript, comments=top_comments,
                suppress_chapters=transcript_is_generated,
                known_content_summary=understanding.content_summary or None,
                keyword_evidence=keyword_evidence, target_audience=understanding.target_audience or None,
                deepseek_api_key=DEEPSEEK_API_KEY,
                duration_seconds=(
                    max(s.start + s.duration for s in transcript_segments) if transcript_segments else None
                ),
            )
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM request failed: {exc}")

        result["target_audience"] = understanding.target_audience
        result["audience_next_question"] = understanding.audience_next_question

        allowed_source = f"{meta.description}\n{transcript or ''}"
        result, scrub_notes = sanitize.scrub(result, allowed_source)
        cacheable, cache_block_reason = sanitize.is_safe_to_cache(result, allowed_source)

        if scrub_notes or not cacheable:
            logger.warning(
                "sanitize: injection evidence on %s -- scrubbed=%s; cacheable=%s (%s)",
                video_id, scrub_notes, cacheable, cache_block_reason,
            )
            warning = (
                "This video's comments or description contained text that tried to steer "
                "the generated output. "
                + ("Suspicious links were removed. " if scrub_notes else "")
                + "Review the description and tags before publishing them."
            )

        if cacheable:
            try:
                analysis_id = db.save_analysis(
                    conn, user["id"], video_id, meta.title, meta.channel_title, result, fingerprint,
                )
            except Exception:
                pass

    # Same safety net as app.py: the model saw the keyword evidence as
    # context but nothing guarantees it echoed the phrases into result["tags"]
    # literally, and a cache hit never saw the evidence at all.
    if keyword_result is not None and not keyword_result.weak_evidence:
        result["tags"] = enforce_tag_char_limit(
            merge_into_tags(result.get("tags", []), keyword_result.strategy)
        )

    report = build_report(
        meta, result,
        top_comments=top_comments, competitors=competitors, include_competitors=body.include_competitors,
        transcript_text=transcript, transcript_segments=transcript_segments, live=True,
        keyword_strategy=keyword_result.strategy if keyword_result is not None else None,
    )
    report["warning"] = warning
    # None on a cache hit -- app.py never wrote a history row for the CURRENT
    # user in that case either (only the original run that populated the
    # cache did), so there is deliberately nothing new for this user to
    # export/reload. Same behavior, just made visible to the frontend instead
    # of silently absent.
    report["analysis_id"] = analysis_id
    return report


# --------------------------------------------------------------------- plan


@app.post("/plan")
def plan(body: PlanRequest, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    """Mirrors app.py's `if run_plan:` block: no real video exists yet, so
    everything is derived from a pasted script rather than fetched metadata."""
    from plan_input import is_plan_input_sufficient

    if not GEMINI_API_KEY:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Server is missing GEMINI_API_KEY")
    if not is_plan_input_sufficient(body.script):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Paste a script or transcript first -- everything else on this form is optional.",
        )

    tags_list = [t.strip() for t in body.tags.split(",") if t.strip()]
    meta = build_planned_meta(
        body.title.strip(), body.description.strip(), tags_list,
        channel_title=f"{user['display_name']} (planned)",
    )
    script_text = body.script.strip() or None

    competitors = []
    if body.include_competitors and YOUTUBE_API_KEY:
        competitors = find_competitors(meta.title, YOUTUBE_API_KEY, exclude_video_id="")

    try:
        understanding = understand_video(
            api_keys=GEMINI_API_KEYS, title=meta.title, description=meta.description,
            existing_tags=meta.tags, transcript=script_text, comments=[],
            deepseek_api_key=DEEPSEEK_API_KEY,
        )
    except Exception as exc:
        logger.warning("understand_video failed in planning mode: %s", exc)
        understanding = VideoUnderstanding()

    keyword_result = None
    if body.run_keyword_pipeline:
        try:
            keyword_result = keyword_pipeline.run(
                api_keys=GEMINI_API_KEYS, content_summary=understanding.content_summary,
                title=meta.title, description=meta.description, existing_tags=meta.tags,
                transcript=script_text, competitors=competitors, planning=True,
                deepseek_api_key=DEEPSEEK_API_KEY, llm_entities=understanding.entities,
            )
        except Exception as exc:
            logger.warning("keyword pipeline failed in planning mode: %s", exc)

    keyword_evidence = None
    if keyword_result is not None and not keyword_result.weak_evidence:
        keyword_evidence = format_keyword_evidence(keyword_result.strategy) or None

    try:
        result = generate_seo(
            api_keys=GEMINI_API_KEYS, title=meta.title, description=meta.description,
            existing_tags=meta.tags, transcript=script_text, comments=[], suppress_chapters=True,
            known_content_summary=understanding.content_summary or None, keyword_evidence=keyword_evidence,
            target_audience=understanding.target_audience or None, deepseek_api_key=DEEPSEEK_API_KEY,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM request failed: {exc}")

    if not meta.title.strip() and result.get("titles"):
        meta.title = result["titles"][0]

    result["target_audience"] = understanding.target_audience
    result["audience_next_question"] = understanding.audience_next_question

    variant_titles = [t.strip() for t in [body.title_variant] if t.strip()][:1]
    variants = [(meta.title, result)]
    for variant_title in variant_titles:
        try:
            variant_result = generate_seo(
                api_keys=GEMINI_API_KEYS, title=variant_title, description=meta.description,
                existing_tags=meta.tags, transcript=script_text, comments=[], suppress_chapters=True,
                known_content_summary=understanding.content_summary or None, keyword_evidence=keyword_evidence,
                target_audience=understanding.target_audience or None, deepseek_api_key=DEEPSEEK_API_KEY,
            )
        except Exception:
            continue
        variants.append((variant_title, variant_result))

    if keyword_result is not None and not keyword_result.weak_evidence:
        result["tags"] = enforce_tag_char_limit(
            merge_into_tags(result.get("tags", []), keyword_result.strategy)
        )

    allowed_source = f"{meta.description}\n{script_text or ''}"
    result, scrub_notes = sanitize.scrub(result, allowed_source)
    warning = None
    if scrub_notes:
        logger.warning("sanitize: scrubbed planning output -- %s", scrub_notes)
        warning = (
            "Some links in the generated output did not come from your script or description "
            "and were removed. Review before publishing."
        )

    analysis_id = None
    try:
        fingerprint = compute_fingerprint(meta.title, meta.description, meta.tags, script_text, [])
        analysis_id = db.save_analysis(
            conn, user["id"], meta.video_id, meta.title, meta.channel_title, result, fingerprint,
        )
    except Exception:
        pass

    report = build_report(
        meta, result, competitors=competitors, include_competitors=body.include_competitors,
        transcript_text=script_text, live=True, planning=True,
        keyword_strategy=keyword_result.strategy if keyword_result is not None else None,
        variants=variants,
    )
    report["warning"] = warning
    report["analysis_id"] = analysis_id
    return report


# --------------------------------------------------------------- thumbnails


@app.post("/thumbnail/critique")
def thumbnail_critique(body: ThumbnailCritiqueRequest, user: dict = Depends(get_current_user)):
    """Costs one Gemini vision call -- same on-demand contract as the old
    "Run thumbnail vision critique" button, not run automatically."""
    import base64

    if body.thumbnail_url:
        critique = critique_thumbnail(GEMINI_API_KEYS, body.thumbnail_url)
    elif body.image_base64:
        image_bytes = base64.b64decode(body.image_base64)
        critique = critique_thumbnail_bytes(GEMINI_API_KEYS, image_bytes, body.mime_type)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide either thumbnail_url or image_base64")
    return critique or {}


@app.post("/thumbnail/generate")
def thumbnail_generate(body: ThumbnailGenerateRequest, user: dict = Depends(get_current_user)):
    """Planning-mode only: writes N visual prompts, renders each via
    Hugging Face, and auto-critiques every one. Costs roughly 1 + 2*N Gemini
    calls, so this only ever runs when the frontend explicitly asks."""
    import base64

    if not HUGGINGFACE_API_KEY:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Server is missing HUGGINGFACE_API_KEY")

    prompts = generate_thumbnail_prompts(GEMINI_API_KEYS, body.title, body.context, count=body.count)
    concepts = []
    for concept in prompts:
        image_bytes = generate_thumbnail_image(HUGGINGFACE_API_KEY, concept.get("prompt", ""))
        if image_bytes is None:
            continue
        critique = critique_thumbnail_bytes(GEMINI_API_KEYS, image_bytes, "image/webp")
        concepts.append({
            "label": concept.get("label", "Concept"),
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": "image/webp",
            "critique": critique or {},
        })
    return {"concepts": concepts}


# ------------------------------------------------------------------- export


@app.get("/export/{analysis_id}.{fmt}")
def export(
    analysis_id: int, fmt: str, user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    from fastapi.responses import Response
    from export import build_csv_export, build_json_export, build_pdf_export

    stored = db.get_analysis(conn, user["id"], analysis_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    # app.py's render_actions is passed the ORIGINAL video title (meta.title
    # / row["title"]), not result["titles"][0] (Gemini's suggested title) --
    # get_analysis only returns result_json, so the row's own title column
    # is fetched separately here to match that.
    row = conn.execute(
        "SELECT title FROM analyses WHERE id = %s AND user_id = %s", (analysis_id, user["id"]),
    ).fetchone()
    title = row[0] if row else ""

    builders = {
        "json": (build_json_export, "application/json"),
        "csv": (build_csv_export, "text/csv"),
        "pdf": (build_pdf_export, "application/pdf"),
    }
    if fmt not in builders:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "format must be json, csv, or pdf")
    builder, media_type = builders[fmt]
    content = builder(title, stored)
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{analysis_id}-seo-report.{fmt}"'},
    )
