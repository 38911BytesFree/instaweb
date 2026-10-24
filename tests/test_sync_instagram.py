"""Unit tests for scripts/sync_instagram.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Self
from unittest.mock import MagicMock

from scripts.sync_instagram import (
    add_hours_iso,
    load_config,
    merge_and_deduplicate,
    normalize_post_item,
    normalize_story_item,
    parse_iso_timestamp,
    sync_archive,
)


class FakeResponse:
    """Minimal mock for requests.Response context manager."""

    def __init__(self, payload: bytes = b"fake-binary-media-bytes") -> None:
        self._payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int = 65536):
        yield self._payload


def make_fake_session() -> MagicMock:
    session = MagicMock()
    session.get.side_effect = lambda *args, **kwargs: FakeResponse()
    return session


def test_parse_iso_timestamp_handles_epoch_and_iso() -> None:
    assert parse_iso_timestamp(1700000000) == "2023-11-14T22:13:20Z"
    assert parse_iso_timestamp("1700000000") == "2023-11-14T22:13:20Z"
    assert parse_iso_timestamp("2026-10-24T12:30:00Z") == "2026-10-24T12:30:00Z"
    assert add_hours_iso("2026-10-24T06:00:00Z", 24) == "2026-10-25T06:00:00Z"


def test_normalize_post_item_carousel_and_video(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    session = make_fake_session()

    raw_carousel: dict[str, Any] = {
        "id": "1001",
        "shortCode": "CAROUSEL123",
        "timestamp": "2026-10-24T10:00:00Z",
        "caption": "Carousel test post",
        "likesCount": 42,
        "commentsCount": 5,
        "childPosts": [
            {
                "type": "Image",
                "displayUrl": "https://cdn.example.com/slide0.jpg",
            },
            {
                "type": "Video",
                "isVideo": True,
                "videoUrl": "https://cdn.example.com/slide1.mp4",
                "displayUrl": "https://cdn.example.com/slide1_thumb.jpg",
            },
        ],
    }

    normalized = normalize_post_item(raw_carousel, docs_dir=docs_dir, session=session)
    assert normalized is not None
    assert normalized["shortcode"] == "CAROUSEL123"
    assert normalized["mediaType"] == "carousel"
    assert len(normalized["media"]) == 2
    assert normalized["media"][0] == {
        "type": "image",
        "localPath": "data/media/posts/CAROUSEL123_0.jpg",
    }
    assert normalized["media"][1] == {
        "type": "video",
        "localPath": "data/media/posts/CAROUSEL123_1.mp4",
        "posterPath": "data/media/posts/CAROUSEL123_1_thumb.jpg",
    }
    assert (docs_dir / "data" / "media" / "posts" / "CAROUSEL123_0.jpg").exists()
    assert (docs_dir / "data" / "media" / "posts" / "CAROUSEL123_1.mp4").exists()


def test_normalize_story_item_image_and_video(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    session = make_fake_session()

    raw_story = {
        "id": "99887766_12345",
        "taken_at": 1700000000,
        "video_versions": [{"url": "https://cdn.example.com/story.mp4"}],
        "image_versions2": {
            "candidates": [{"url": "https://cdn.example.com/story_thumb.jpg"}]
        },
    }

    story = normalize_story_item(
        raw_story,
        username="yukipanvel",
        docs_dir=docs_dir,
        session=session,
    )
    assert story is not None
    assert story["id"] == "99887766"
    assert story["mediaType"] == "video"
    assert story["localPath"] == "data/media/stories/99887766.mp4"
    assert story["thumbnailPath"] == "data/media/stories/99887766_thumb.jpg"
    assert story["expiresAt"] == "2023-11-15T22:13:20Z"


def test_merge_and_deduplicate_orders_newest_first() -> None:
    existing = [
        {"id": "1", "takenAt": "2026-10-20T00:00:00Z"},
        {"id": "2", "takenAt": "2026-10-22T00:00:00Z"},
    ]
    incoming = [
        {"id": "2", "takenAt": "2026-10-22T00:00:00Z"},
        {"id": "3", "takenAt": "2026-10-24T00:00:00Z"},
    ]
    merged, added = merge_and_deduplicate(existing, incoming, key_field="id")
    assert added == 1
    assert [item["id"] for item in merged] == ["3", "2", "1"]


def test_sync_archive_end_to_end_and_idempotent(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    archive_path = docs_dir / "data" / "archive.json"
    session = make_fake_session()

    config = load_config(tmp_path / "nonexistent.json")
    config["targetUsername"] = "testaccount"

    raw_posts = [
        {
            "id": "p1",
            "shortCode": "POST_A",
            "timestamp": "2026-10-24T08:00:00Z",
            "caption": "Hello world",
            "displayUrl": "https://cdn.example.com/post_a.jpg",
            "ownerFullName": "Test Account",
            "ownerProfilePicUrl": "https://cdn.example.com/avatar.jpg",
        }
    ]
    raw_stories = [
        {
            "id": "s1",
            "timestamp": "2026-10-24T09:00:00Z",
            "displayUrl": "https://cdn.example.com/story_1.jpg",
        }
    ]

    result1 = sync_archive(
        config=config,
        raw_posts=raw_posts,
        raw_stories=raw_stories,
        docs_dir=docs_dir,
        archive_path=archive_path,
        session=session,
    )
    assert len(result1["posts"]) == 1
    assert len(result1["stories"]) == 1
    assert result1["profile"]["username"] == "testaccount"
    assert result1["profile"]["fullName"] == "Test Account"
    assert archive_path.exists()

    # Running a second time with the same items should skip re-downloading post/story media
    call_count_after_first = session.get.call_count
    result2 = sync_archive(
        config=config,
        raw_posts=raw_posts,
        raw_stories=raw_stories,
        docs_dir=docs_dir,
        archive_path=archive_path,
        session=session,
    )
    assert len(result2["posts"]) == 1
    assert len(result2["stories"]) == 1
    # Only the profile avatar is refreshed; post & story media are skipped
    assert session.get.call_count == call_count_after_first + 1

    saved_json = json.loads(archive_path.read_text(encoding="utf-8"))
    assert saved_json["posts"][0]["shortcode"] == "POST_A"
    assert saved_json["stories"][0]["id"] == "s1"

    # Changing targetUsername should clear previous user's items and profile metadata
    config["targetUsername"] = "yukipanvel"
    result3 = sync_archive(
        config=config,
        raw_posts=[],
        raw_stories=[],
        docs_dir=docs_dir,
        archive_path=archive_path,
        session=session,
    )
    assert result3["profile"]["username"] == "yukipanvel"
    assert result3["profile"]["fullName"] == "yukipanvel"
    assert result3["posts"] == []
    assert result3["stories"] == []
