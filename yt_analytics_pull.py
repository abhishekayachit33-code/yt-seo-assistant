"""Pull LetzStudy's real YouTube search-terms data via the Analytics API.

Standalone local analysis tool, deliberately NOT imported by the app:
- It needs OAuth (owner-only private analytics), unlike everything else in
  this project which uses a plain API key for public Data API reads.
- Its deps (google-auth-oauthlib, google-api-python-client) stay out of
  requirements.txt so the deployed image doesn't carry an auth stack it
  never uses.

Purpose: get ground truth on which search queries actually drove views to
which video, so the keyword pipeline's predictions can be backtested against
real outcomes rather than assumed to work.

Usage:
    python3 yt_analytics_pull.py auth      # one-time, opens browser to consent
    python3 yt_analytics_pull.py channel   # channel-wide search terms
    python3 yt_analytics_pull.py video <VIDEO_ID>
    python3 yt_analytics_pull.py top [N]   # per-video terms for top N videos
"""

import csv
import json
import os
import sys
from datetime import date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read-only. Deliberately the narrowest scope that works -- this tool never
# needs to modify anything on the channel.
SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]

TOKEN_FILE = "yt_analytics_token.json"
CLIENT_SECRET_GLOB = "client_secret"

# Analytics data doesn't exist before the channel did; this is early enough
# to mean "lifetime" for any realistic channel while satisfying the API's
# required start date.
LIFETIME_START = "2005-02-14"


def _find_client_secret() -> str:
    for name in os.listdir("."):
        if name.startswith(CLIENT_SECRET_GLOB) and name.endswith(".json"):
            return name
    raise SystemExit(
        "No client_secret*.json found in this directory.\n"
        "Download it from Google Cloud Console -> APIs & Services -> Credentials."
    )


def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(_find_client_secret(), SCOPES)
        creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)  # refresh token -- owner-read only
    return creds


def _client():
    return build("youtubeAnalytics", "v2", credentials=get_credentials())


def _query(**kwargs) -> dict:
    params = {
        "ids": "channel==MINE",
        "startDate": LIFETIME_START,
        "endDate": date.today().isoformat(),
    }
    params.update(kwargs)
    return _client().reports().query(**params).execute()


def _write_csv(rows: list, headers: list[str], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}")


def channel_search_terms() -> None:
    """Channel-wide: which queries drove views, across all videos."""
    resp = _query(
        dimensions="insightTrafficSourceDetail",
        metrics="views,estimatedMinutesWatched",
        filters="insightTrafficSourceType==YT_SEARCH",
        sort="-views",
        maxResults=200,
    )
    rows = resp.get("rows", [])
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    _write_csv(rows, headers, "letzstudy_search_terms_channel.csv")
    total = sum(r[1] for r in rows)
    print(f"\ntop 25 of {len(rows)} terms ({total} search views total):")
    for term, views, *_ in rows[:25]:
        print(f"  {views:>5}  {term}")


def video_search_terms(video_id: str, quiet: bool = False) -> list:
    """Which queries drove views to ONE video -- the mapping the backtest needs."""
    resp = _query(
        dimensions="insightTrafficSourceDetail",
        metrics="views",
        filters=f"video=={video_id};insightTrafficSourceType==YT_SEARCH",
        sort="-views",
        maxResults=50,
    )
    rows = resp.get("rows", [])
    if not quiet:
        print(f"{video_id}: {len(rows)} search terms")
        for term, views in rows[:15]:
            print(f"  {views:>4}  {term}")
    return rows


def top_videos_search_terms(limit: int = 10) -> None:
    """Per-video terms for the top N videos by views. The low-view tail gets
    bucketed into 'Other' by YouTube anyway, so pulling all ~114 mostly
    yields noise -- this targets the videos with enough volume to be real."""
    resp = _query(
        dimensions="video", metrics="views", sort="-views", maxResults=limit,
    )
    videos = resp.get("rows", [])
    print(f"pulling search terms for top {len(videos)} videos...\n")

    out = []
    for video_id, views in videos:
        terms = video_search_terms(video_id, quiet=True)
        print(f"  {video_id}  ({views} views)  -> {len(terms)} search terms")
        for term, term_views in terms:
            out.append([video_id, views, term, term_views])

    _write_csv(
        out, ["video_id", "video_views", "search_term", "term_views"],
        "letzstudy_search_terms_by_video.csv",
    )


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "channel"
    if cmd == "auth":
        get_credentials()
        print("authorized -- token saved to " + TOKEN_FILE)
    elif cmd == "channel":
        channel_search_terms()
    elif cmd == "video":
        video_search_terms(sys.argv[2])
    elif cmd == "top":
        top_videos_search_terms(int(sys.argv[3]) if len(sys.argv) > 3 else 10)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
