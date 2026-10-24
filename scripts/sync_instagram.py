#!/usr/bin/env python3
"""Synchronize public Instagram Posts and Stories via Apify into docs/data/.

Downloads media files locally so expiring Instagram CDN URLs do not break
the static GitHub Pages site, deduplicates by item ID, and writes the
normalized manifest to docs/data/archive.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from apify_client import ApifyClient
except ImportError:  # pragma: no cover - fallback when apify_client is mocked in tests
    ApifyClient = None  # type: ignore[assignment,misc]

LOGGER = logging.getLogger("sync_instagram")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.json"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHIVE_PATH = DEFAULT_DOCS_DIR / "data" / "archive.json"


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load configuration from config.json and apply environment variable overrides."""
    config: dict[str, Any] = {
        "targetUsername": "yukipanvel",
        "postsActorId": "apify/instagram-post-scraper",
        "storiesActorId": "apify/instagram-story-scraper",
        "resultsLimit": 12,
        "fetchPosts": True,
        "fetchStories": True,
        "maxArchivedPosts": 0,
        "maxArchivedStories": 0,
        "downloadTimeoutSeconds": 60,
    }
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
            if isinstance(loaded, dict):
                config.update(loaded)

    env_username = os.environ.get("IG_TARGET_USERNAME", "").strip()
    if env_username:
        config["targetUsername"] = env_username.lstrip("@")

    env_posts_actor = os.environ.get("APIFY_POSTS_ACTOR_ID", "").strip()
    if env_posts_actor:
        config["postsActorId"] = env_posts_actor

    env_stories_actor = os.environ.get("APIFY_STORIES_ACTOR_ID", "").strip()
    if env_stories_actor:
        config["storiesActorId"] = env_stories_actor

    return config


def load_archive(archive_path: Path = DEFAULT_ARCHIVE_PATH) -> dict[str, Any]:
    """Load existing archive.json or initialize an empty manifest."""
    if archive_path.exists():
        try:
            with archive_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    data.setdefault("profile", {})
                    data.setdefault("stories", [])
                    data.setdefault("posts", [])
                    return data
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning(
                "Could not parse existing archive.json (%s); starting fresh.", exc
            )

    return {
        "profile": {
            "username": "",
            "fullName": "",
            "biography": "",
            "avatarLocalPath": "",
            "lastUpdatedUtc": "",
        },
        "stories": [],
        "posts": [],
    }


def parse_iso_timestamp(raw_value: Any) -> str:
    """Normalize various timestamp formats (ISO string or Unix epoch) into UTC ISO-8601."""
    if raw_value is None or raw_value == "":
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(raw_value, (int, float)):
        dt = datetime.fromtimestamp(float(raw_value), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    raw_str = str(raw_value).strip()
    if raw_str.isdigit():
        dt = datetime.fromtimestamp(float(raw_str), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        normalized = raw_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_hours_iso(iso_ts: str, hours: int = 24) -> str:
    """Add hours to an ISO-8601 UTC timestamp string."""
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    exp = dt + timedelta(hours=hours)
    return exp.strftime("%Y-%m-%dT%H:%M:%SZ")


def download_file(
    url: str,
    dest_path: Path,
    timeout: int = 60,
    session: requests.Session | None = None,
) -> bool:
    """Download a binary file from a URL to dest_path atomically if not already present."""
    if not url:
        return False

    if dest_path.exists() and dest_path.stat().st_size > 0:
        LOGGER.debug("Skipping existing media file: %s", dest_path)
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    http = session or requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        with http.get(url, headers=headers, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with tmp_path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        fh.write(chunk)
        tmp_path.replace(dest_path)
        LOGGER.info("Downloaded %s", dest_path.relative_to(dest_path.parents[3]))
        return True
    except (requests.RequestException, OSError) as exc:
        LOGGER.warning("Failed to download %s -> %s: %s", url, dest_path, exc)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False


def _extract_first_url(item: dict[str, Any], keys: list[str]) -> str:
    """Return the first non-empty string URL found across candidate keys."""
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    # Handle nested Instagram Graph / API structures (image_versions2 / video_versions)
    if "video_versions" in item and isinstance(item["video_versions"], list):
        for candidate in item["video_versions"]:
            if isinstance(candidate, dict) and isinstance(candidate.get("url"), str):
                return candidate["url"]
    if "image_versions2" in item and isinstance(item["image_versions2"], dict):
        candidates = item["image_versions2"].get("candidates", [])
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict) and isinstance(
                    candidate.get("url"), str
                ):
                    return candidate["url"]
    return ""


def normalize_post_item(
    raw: dict[str, Any],
    docs_dir: Path,
    timeout: int = 60,
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    """Normalize a raw Apify post item and download its media assets into docs/data/media/posts/."""
    shortcode = str(
        raw.get("shortCode")
        or raw.get("shortcode")
        or raw.get("code")
        or raw.get("id")
        or ""
    ).strip()
    if not shortcode:
        return None

    post_id = str(raw.get("id") or shortcode).strip()
    taken_at = parse_iso_timestamp(
        raw.get("timestamp")
        or raw.get("takenAt")
        or raw.get("taken_at_timestamp")
        or raw.get("taken_at")
    )
    caption = str(raw.get("caption") or raw.get("captionText") or "").strip()
    if isinstance(raw.get("caption"), dict):
        caption = str(raw["caption"].get("text") or "").strip()

    likes_count = int(raw.get("likesCount") or raw.get("like_count") or 0)
    comments_count = int(raw.get("commentsCount") or raw.get("comment_count") or 0)
    permalink = str(
        raw.get("url")
        or raw.get("permalink")
        or f"https://www.instagram.com/p/{shortcode}/"
    ).strip()

    # Determine child items for carousels / sidecars
    children = (
        raw.get("childPosts")
        or raw.get("carousel_media")
        or raw.get("sidecarChildren")
        or []
    )

    media_entries: list[dict[str, str]] = []
    posts_media_dir = docs_dir / "data" / "media" / "posts"

    if isinstance(children, list) and len(children) > 0:
        for idx, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            media_entry = _download_single_post_media(
                child, shortcode, idx, posts_media_dir, timeout, session
            )
            if media_entry:
                media_entries.append(media_entry)
    else:
        media_entry = _download_single_post_media(
            raw, shortcode, 0, posts_media_dir, timeout, session
        )
        if media_entry:
            media_entries.append(media_entry)

    if not media_entries:
        return None

    if len(media_entries) > 1:
        media_type = "carousel"
    elif media_entries[0]["type"] == "video":
        media_type = "video"
    else:
        media_type = "image"

    return {
        "id": post_id,
        "shortcode": shortcode,
        "takenAt": taken_at,
        "caption": caption,
        "likesCount": likes_count,
        "commentsCount": comments_count,
        "mediaType": media_type,
        "permalink": permalink,
        "media": media_entries,
    }


def _download_single_post_media(
    item: dict[str, Any],
    shortcode: str,
    index: int,
    posts_media_dir: Path,
    timeout: int,
    session: requests.Session | None,
) -> dict[str, str] | None:
    """Download a single slide/post media file (video + poster or image)."""
    is_video = bool(
        item.get("isVideo")
        or str(item.get("type", "")).lower() == "video"
        or item.get("media_type") == 2
        or item.get("videoUrl")
        or item.get("video_versions")
    )
    video_url = _extract_first_url(item, ["videoUrl", "video_url"])
    image_url = _extract_first_url(
        item,
        [
            "displayUrl",
            "display_url",
            "imageUrl",
            "image_url",
            "thumbnailUrl",
            "thumbnail_src",
        ],
    )

    if is_video and video_url:
        video_filename = f"{shortcode}_{index}.mp4"
        video_dest = posts_media_dir / video_filename
        if download_file(video_url, video_dest, timeout=timeout, session=session):
            entry: dict[str, str] = {
                "type": "video",
                "localPath": f"data/media/posts/{video_filename}",
            }
            if image_url:
                poster_filename = f"{shortcode}_{index}_thumb.jpg"
                poster_dest = posts_media_dir / poster_filename
                if download_file(
                    image_url, poster_dest, timeout=timeout, session=session
                ):
                    entry["posterPath"] = f"data/media/posts/{poster_filename}"
            return entry

    if image_url:
        img_filename = f"{shortcode}_{index}.jpg"
        img_dest = posts_media_dir / img_filename
        if download_file(image_url, img_dest, timeout=timeout, session=session):
            return {
                "type": "image",
                "localPath": f"data/media/posts/{img_filename}",
            }

    return None


def normalize_story_item(
    raw: dict[str, Any],
    username: str,
    docs_dir: Path,
    timeout: int = 60,
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    """Normalize a raw Apify story item and download its media into docs/data/media/stories/."""
    story_id = str(
        raw.get("id") or raw.get("pk") or raw.get("storyId") or raw.get("code") or ""
    ).strip()
    if not story_id:
        return None

    # Strip composite user suffix if present (e.g. "123456789_987654")
    clean_id = story_id.split("_")[0]

    taken_at = parse_iso_timestamp(
        raw.get("timestamp")
        or raw.get("takenAt")
        or raw.get("taken_at")
        or raw.get("taken_at_timestamp")
    )
    expires_raw = (
        raw.get("expiringAt") or raw.get("expiring_at") or raw.get("expiresAt")
    )
    expires_at = (
        parse_iso_timestamp(expires_raw) if expires_raw else add_hours_iso(taken_at, 24)
    )

    is_video = bool(
        raw.get("isVideo")
        or str(raw.get("type", "")).lower() == "video"
        or raw.get("media_type") == 2
        or raw.get("videoUrl")
        or raw.get("video_versions")
    )
    video_url = _extract_first_url(raw, ["videoUrl", "video_url"])
    image_url = _extract_first_url(
        raw,
        ["displayUrl", "display_url", "imageUrl", "image_url", "thumbnailUrl"],
    )

    stories_media_dir = docs_dir / "data" / "media" / "stories"
    local_path = ""
    thumbnail_path = ""
    media_type = "image"

    if is_video and video_url:
        video_filename = f"{clean_id}.mp4"
        video_dest = stories_media_dir / video_filename
        if download_file(video_url, video_dest, timeout=timeout, session=session):
            media_type = "video"
            local_path = f"data/media/stories/{video_filename}"
            if image_url:
                thumb_filename = f"{clean_id}_thumb.jpg"
                thumb_dest = stories_media_dir / thumb_filename
                if download_file(
                    image_url, thumb_dest, timeout=timeout, session=session
                ):
                    thumbnail_path = f"data/media/stories/{thumb_filename}"
    elif image_url:
        img_filename = f"{clean_id}.jpg"
        img_dest = stories_media_dir / img_filename
        if download_file(image_url, img_dest, timeout=timeout, session=session):
            media_type = "image"
            local_path = f"data/media/stories/{img_filename}"
            thumbnail_path = local_path

    if not local_path:
        return None

    return {
        "id": clean_id,
        "takenAt": taken_at,
        "expiresAt": expires_at,
        "mediaType": media_type,
        "localPath": local_path,
        "thumbnailPath": thumbnail_path or local_path,
        "caption": str(raw.get("caption") or "").strip(),
        "originalPermalink": f"https://www.instagram.com/stories/{username}/{clean_id}/",
    }


def extract_profile_metadata(
    raw_items: list[dict[str, Any]],
    username: str,
    existing_profile: dict[str, Any],
    docs_dir: Path,
    timeout: int = 60,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Update profile metadata (name, bio, avatar) from raw Apify items."""
    same_user = existing_profile.get("username") == username
    profile = {
        "username": username,
        "fullName": (existing_profile.get("fullName") if same_user else "") or username,
        "biography": (existing_profile.get("biography") if same_user else "") or "",
        "avatarLocalPath": (
            existing_profile.get("avatarLocalPath") if same_user else ""
        )
        or "",
        "lastUpdatedUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    avatar_url = ""
    for item in raw_items:
        owner = item.get("owner") or item.get("user") or {}
        if isinstance(owner, dict):
            full_name = owner.get("full_name") or owner.get("fullName")
            if full_name:
                profile["fullName"] = str(full_name)
            bio = owner.get("biography")
            if bio:
                profile["biography"] = str(bio)
            pic = (
                owner.get("profile_pic_url_hd")
                or owner.get("profile_pic_url")
                or owner.get("profilePicUrl")
            )
            if isinstance(pic, str) and pic.startswith("http"):
                avatar_url = pic

        if item.get("ownerFullName"):
            profile["fullName"] = str(item["ownerFullName"])
        if item.get("biography"):
            profile["biography"] = str(item["biography"])
        top_pic = item.get("ownerProfilePicUrl") or item.get("profilePicUrl")
        if isinstance(top_pic, str) and top_pic.startswith("http"):
            avatar_url = top_pic

    if avatar_url:
        avatar_dest = docs_dir / "data" / "media" / "profile" / f"{username}_avatar.jpg"
        # Force refresh avatar when URL is present
        if avatar_dest.exists():
            avatar_dest.unlink(missing_ok=True)
        if download_file(avatar_url, avatar_dest, timeout=timeout, session=session):
            profile["avatarLocalPath"] = f"data/media/profile/{username}_avatar.jpg"

    return profile


def fetch_apify_posts(
    client: Any,
    actor_id: str,
    username: str,
    results_limit: int,
) -> list[dict[str, Any]]:
    """Run the configured Apify Posts Actor and return raw dataset items."""
    LOGGER.info(
        "Running Apify Posts Actor '%s' for @%s (limit=%d)...",
        actor_id,
        username,
        results_limit,
    )
    run_input = {
        "username": [username],
        "usernames": [username],
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsLimit": results_limit,
        "resultsType": "posts",
    }
    run = client.actor(actor_id).call(run_input=run_input)
    if not run or "defaultDatasetId" not in run:
        LOGGER.warning("Posts Actor '%s' returned no dataset.", actor_id)
        return []
    dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items
    LOGGER.info("Posts Actor returned %d raw items.", len(dataset_items))
    return [item for item in dataset_items if isinstance(item, dict)]


def fetch_apify_stories(
    client: Any,
    actor_id: str,
    username: str,
) -> list[dict[str, Any]]:
    """Run the configured Apify Stories Actor and return raw dataset items."""
    LOGGER.info("Running Apify Stories Actor '%s' for @%s...", actor_id, username)
    run_input = {
        "usernames": [username],
        "username": [username],
        "profiles": [username],
        "directUrls": [f"https://www.instagram.com/{username}/"],
    }
    run = client.actor(actor_id).call(run_input=run_input)
    if not run or "defaultDatasetId" not in run:
        LOGGER.warning("Stories Actor '%s' returned no dataset.", actor_id)
        return []
    dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items
    # Unpack nested stories array if the actor wraps stories inside a profile object
    flattened: list[dict[str, Any]] = []
    for item in dataset_items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("stories"), list):
            for story in item["stories"]:
                if isinstance(story, dict):
                    flattened.append(story)
        elif isinstance(item.get("items"), list):
            for story in item["items"]:
                if isinstance(story, dict):
                    flattened.append(story)
        else:
            flattened.append(item)

    LOGGER.info("Stories Actor returned %d raw story items.", len(flattened))
    return flattened


def merge_and_deduplicate(
    existing_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    key_field: str = "id",
    max_items: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Merge existing and newly normalized items, deduplicating by key_field and sorting newest first."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing_items:
        item_id = str(item.get(key_field, "")).strip()
        if item_id:
            by_id[item_id] = item

    added_count = 0
    for item in new_items:
        item_id = str(item.get(key_field, "")).strip()
        if not item_id:
            continue
        if item_id not in by_id:
            added_count += 1
        by_id[item_id] = item

    merged = sorted(
        by_id.values(),
        key=lambda x: str(x.get("takenAt", "")),
        reverse=True,
    )
    if max_items and max_items > 0:
        merged = merged[:max_items]
    return merged, added_count


def sync_archive(
    config: dict[str, Any],
    raw_posts: list[dict[str, Any]],
    raw_stories: list[dict[str, Any]],
    docs_dir: Path = DEFAULT_DOCS_DIR,
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Process raw Apify posts & stories, download media, and save updated archive.json."""
    archive = load_archive(archive_path)
    username = str(config.get("targetUsername", "yukipanvel")).lstrip("@")
    timeout = int(config.get("downloadTimeoutSeconds", 60))

    # If the configured targetUsername changed from what was previously stored in archive.json,
    # reset old stories/posts so data from a previous account never leaks in.
    previous_username = str(archive.get("profile", {}).get("username") or "").strip()
    if previous_username and previous_username != username:
        LOGGER.info(
            "Target username changed from '%s' to '%s'; resetting archived items.",
            previous_username,
            username,
        )
        archive["stories"] = []
        archive["posts"] = []
        archive["profile"] = {"username": username}

    existing_post_ids = {
        str(p.get("shortcode") or p.get("id")) for p in archive.get("posts", [])
    }
    existing_story_ids = {str(s.get("id")) for s in archive.get("stories", [])}

    normalized_posts: list[dict[str, Any]] = []
    for raw_post in raw_posts:
        candidate_code = str(
            raw_post.get("shortCode")
            or raw_post.get("shortcode")
            or raw_post.get("code")
            or raw_post.get("id")
            or ""
        ).strip()
        if candidate_code and candidate_code in existing_post_ids:
            LOGGER.debug(
                "Post %s already archived; skipping media download.", candidate_code
            )
            continue
        post = normalize_post_item(
            raw_post, docs_dir=docs_dir, timeout=timeout, session=session
        )
        if post:
            normalized_posts.append(post)

    normalized_stories: list[dict[str, Any]] = []
    for raw_story in raw_stories:
        candidate_id = str(
            raw_story.get("id") or raw_story.get("pk") or raw_story.get("storyId") or ""
        ).split("_")[0]
        if candidate_id and candidate_id in existing_story_ids:
            LOGGER.debug(
                "Story %s already archived; skipping media download.", candidate_id
            )
            continue
        story = normalize_story_item(
            raw_story,
            username=username,
            docs_dir=docs_dir,
            timeout=timeout,
            session=session,
        )
        if story:
            normalized_stories.append(story)

    merged_posts, new_posts_count = merge_and_deduplicate(
        archive.get("posts", []),
        normalized_posts,
        key_field="shortcode",
        max_items=int(config.get("maxArchivedPosts", 0)),
    )
    merged_stories, new_stories_count = merge_and_deduplicate(
        archive.get("stories", []),
        normalized_stories,
        key_field="id",
        max_items=int(config.get("maxArchivedStories", 0)),
    )

    profile = extract_profile_metadata(
        raw_posts + raw_stories,
        username=username,
        existing_profile=archive.get("profile", {}),
        docs_dir=docs_dir,
        timeout=timeout,
        session=session,
    )

    updated_archive = {
        "profile": profile,
        "stories": merged_stories,
        "posts": merged_posts,
    }

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("w", encoding="utf-8") as fh:
        json.dump(updated_archive, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    LOGGER.info(
        "Archive updated: +%d new stories (%d total), +%d new posts (%d total).",
        new_stories_count,
        len(merged_stories),
        new_posts_count,
        len(merged_posts),
    )
    return updated_archive


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for running the Apify Instagram sync."""
    parser = argparse.ArgumentParser(
        description="Sync public Instagram Posts & Stories via Apify."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.json",
    )
    parser.add_argument(
        "--username",
        type=str,
        default="",
        help="Override target Instagram username",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    config = load_config(args.config)
    if args.username:
        config["targetUsername"] = args.username.lstrip("@")

    api_token = os.environ.get("APIFY_API_TOKEN", "").strip()
    if not api_token:
        LOGGER.error(
            "Missing APIFY_API_TOKEN environment variable. "
            "Set it in your GitHub Repository Secrets or local environment."
        )
        return 1

    if ApifyClient is None:
        LOGGER.error(
            "apify-client is not installed. Run: pip install -r scripts/requirements.txt"
        )
        return 1

    client = ApifyClient(api_token)
    username = str(config["targetUsername"]).lstrip("@")

    raw_posts: list[dict[str, Any]] = []
    raw_stories: list[dict[str, Any]] = []

    if config.get("fetchPosts", True):
        try:
            raw_posts = fetch_apify_posts(
                client,
                actor_id=str(config["postsActorId"]),
                username=username,
                results_limit=int(config.get("resultsLimit", 12)),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Error fetching posts from Apify: %s", exc)

    if config.get("fetchStories", True):
        try:
            raw_stories = fetch_apify_stories(
                client,
                actor_id=str(config["storiesActorId"]),
                username=username,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Error fetching stories from Apify: %s", exc)

    sync_archive(config=config, raw_posts=raw_posts, raw_stories=raw_stories)
    return 0


if __name__ == "__main__":
    sys.exit(main())
