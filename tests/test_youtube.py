import re

import pytest

from youtube import InvalidURLError, build_planned_meta, parse_video_id

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PL123&index=3",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?si=abc123",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        VIDEO_ID,
        f"  {VIDEO_ID}  ",
    ],
)
def test_parse_video_id_accepts_known_shapes(url):
    assert parse_video_id(url) == VIDEO_ID


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://www.youtube.com/watch?v=",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=short",
    ],
)
def test_parse_video_id_rejects_invalid_input(url):
    with pytest.raises(InvalidURLError):
        parse_video_id(url)


def test_planned_meta_is_flagged_and_has_empty_real_video_fields():
    meta = build_planned_meta("A draft title", "A draft description", ["draft tag"], "Some Channel")
    assert meta.is_planned is True
    assert meta.title == "A draft title"
    assert meta.description == "A draft description"
    assert meta.tags == ["draft tag"]
    assert meta.channel_title == "Some Channel"
    assert meta.thumbnail_url == ""
    assert meta.published_at == ""
    assert meta.view_count == 0
    assert meta.like_count == 0
    assert meta.comment_count == 0
    assert meta.category_id == ""


def test_planned_video_id_can_never_collide_with_a_real_one():
    # Real YouTube IDs are exactly 11 chars of [A-Za-z0-9_-] (parse_video_id's
    # own pattern) -- a planned ID must never accidentally match that shape,
    # since video_id doubles as the "is this planned" signal on history reload.
    meta = build_planned_meta("t", "d", [], "c")
    assert meta.video_id.startswith("planned-")
    assert not re.fullmatch(r"[A-Za-z0-9_-]{11}", meta.video_id)


def test_planned_video_ids_are_unique_per_call():
    first = build_planned_meta("t", "d", [], "c")
    second = build_planned_meta("t", "d", [], "c")
    assert first.video_id != second.video_id


def test_fetch_metadata_defaults_is_planned_false():
    from youtube import VideoMeta
    meta = VideoMeta(
        video_id=VIDEO_ID, title="t", description="d", tags=[], channel_title="c", thumbnail_url="",
    )
    assert meta.is_planned is False
