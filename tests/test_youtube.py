import pytest

from youtube import InvalidURLError, parse_video_id

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
