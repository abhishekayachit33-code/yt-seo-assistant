"""Thumbnail concept generation for the planning flow -- two separate calls:
Gemini writes 2-3 distinct visual concepts (prompts) from the video's title
and context, then each prompt is rendered to an actual image via Hugging
Face's Inference Providers router, model stabilityai/stable-diffusion-3.5-medium.
Kept as two functions, not one, because they're two different failure domains
(JSON schema call vs. raw image fetch) and the caller needs to keep going on
the prompts even if one image render fails.
"""

import json
import time

import requests
from google.genai import types

from gemini_client import generate_content_with_fallback
from llm import MODEL

# stable-diffusion-3.5-medium is not served by HF's own "hf-inference"
# provider (confirmed live: that endpoint 400s with "Model not supported by
# provider hf-inference") -- it's only live through the "replicate" provider
# in HF's Inference Providers router. That provider speaks Replicate's own
# API shape, not HF's unified text-to-image shape: POST creates a prediction
# job, `Prefer: wait` blocks up to ~60s for it to finish inline, and on
# success the response carries an `output` URL to fetch -- not the image
# bytes directly. Confirmed against the live API before writing this,
# because the docs alone don't make the shape difference obvious.
_HF_REPLICATE_PREDICTIONS_URL = (
    "https://router.huggingface.co/replicate/v1/models/"
    "stability-ai/stable-diffusion-3.5-medium/predictions"
)

_POLL_INTERVAL_SECONDS = 2
_POLL_MAX_ATTEMPTS = 15  # ~30s ceiling if `Prefer: wait` times out before completion

_PROMPT_SYSTEM = """
You are a YouTube thumbnail art director. Given a video's title and context,
propose distinct visual concepts an image model can render.

Rules:
- Each concept is a single self-contained image-generation prompt: subject,
  composition, lighting, color grade, style. Be concrete and visual.
- Do NOT ask the image model to render any specific text/words -- image
  models render text unreliably. Instead, describe the scene so roughly one
  third of the frame (left or right) is visually simple/uncluttered, since a
  title will be overlaid there afterward in an editor.
- Vary the concepts meaningfully from each other (different subject framing,
  different color mood, different composition) -- not the same idea reworded.
- Optimize for a small, busy YouTube feed: high contrast, one clear focal
  subject, no clutter.
"""

_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["label", "prompt"],
            },
        },
    },
    "required": ["concepts"],
}


def generate_thumbnail_prompts(api_keys: list[str], title: str, context: str, count: int = 3) -> list[dict]:
    """One Gemini call. Returns up to `count` {label, prompt} dicts, or an
    empty list on failure -- this is a nice-to-have, never worth breaking the
    planning flow over."""
    user_prompt = f"Title: {title}\n\nContext: {context[:1500]}\n\nPropose {count} thumbnail concepts."
    try:
        response = generate_content_with_fallback(
            api_keys,
            model=MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_PROMPT_SYSTEM,
                response_mime_type="application/json",
                response_schema=_PROMPT_SCHEMA,
                temperature=0.8,
            ),
        )
        data = json.loads(response.text)
        return data.get("concepts", [])[:count]
    except Exception:
        return []


def _create_prediction(hf_token: str, prompt: str, aspect_ratio: str) -> dict:
    response = requests.post(
        _HF_REPLICATE_PREDICTIONS_URL,
        headers={
            "Authorization": f"Bearer {hf_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        },
        json={"input": {"prompt": prompt, "aspect_ratio": aspect_ratio}},
        timeout=65,
    )
    response.raise_for_status()
    return response.json()


def _poll_until_done(hf_token: str, get_url: str) -> dict | None:
    for _ in range(_POLL_MAX_ATTEMPTS):
        time.sleep(_POLL_INTERVAL_SECONDS)
        response = requests.get(get_url, headers={"Authorization": f"Bearer {hf_token}"}, timeout=30)
        response.raise_for_status()
        prediction = response.json()
        if prediction.get("status") in ("succeeded", "failed", "canceled"):
            return prediction
    return None


def generate_thumbnail_image(hf_token: str, prompt: str, aspect_ratio: str = "16:9") -> bytes | None:
    """Raw image bytes from Hugging Face's stable-diffusion-3.5-medium (via
    the replicate provider), or None on any failure -- this is a nice-to-have,
    never worth blocking the planning flow over. `Prefer: wait` usually
    resolves inline within a few seconds; the poll loop only kicks in if that
    times out before the job finishes."""
    if not hf_token or not prompt:
        return None
    try:
        prediction = _create_prediction(hf_token, prompt, aspect_ratio)
        if prediction.get("status") not in ("succeeded", "failed", "canceled"):
            prediction = _poll_until_done(hf_token, prediction["urls"]["get"])
        if prediction is None or prediction.get("status") != "succeeded" or not prediction.get("output"):
            return None
        image_response = requests.get(prediction["output"], timeout=30)
        image_response.raise_for_status()
        return image_response.content
    except (requests.exceptions.RequestException, KeyError):
        return None
