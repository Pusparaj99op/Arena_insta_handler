"""Content publishing: images, carousels, Reels (and Stories) through the API.

The flow is more annoying than it looks, so it lives in one file:

    media_url -> create container -> poll status_code until FINISHED
              -> media_publish -> published media id

Things that bite in production, all handled here:

* Containers expire 24h after creation. We never create one early; the
  scheduler creates it minutes before the slot, not days.
* `status_code` is only meaningful for video. For images it is absent and the
  publish call works immediately.
* A video container can report ERROR with no message. We surface the subcode
  and tell the operator what to fix rather than retrying for an hour.
* Publishing counts against a rolling 24h quota that is 100 on one Meta page
  and 50 on another. We ask the API, not the docs.
* `share_to_feed` on Reels: without it the Reel does not appear on the profile
  grid, which is not what anybody means by "post a reel".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, store
from .graph import Client, GraphError


class PublishError(RuntimeError):
    pass


@dataclass
class Media:
    """An image or video ready to publish, addressed by public URL."""
    url: str
    kind: str                 # IMAGE | VIDEO | REELS | STORIES
    is_carousel_item: bool = False


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------
def _create_container(client: Client, *, params: dict[str, Any], what: str) -> str:
    payload = client.post(f"{client.graph.user_id}/media", **params)
    container_id = payload.get("id")
    if not container_id:
        raise PublishError(f"Meta accepted the {what} request but returned no container id: "
                           f"{payload}")
    return container_id


def _await_container(client: Client, container_id: str, *, timeout: int = 600,
                     interval: int = 5) -> str:
    """Poll until the container is FINISHED. Video only, images pass straight through."""
    deadline = time.monotonic() + timeout
    last = "unknown"
    while time.monotonic() < deadline:
        payload = client.get(container_id, fields="status_code,status,id")
        last = str(payload.get("status_code") or payload.get("status") or "unknown")
        if last == "FINISHED":
            return container_id
        if last in {"ERROR", "EXPIRED"}:
            detail = payload.get("status") or "no detail from Meta"
            raise PublishError(
                f"Container {container_id} went {last}: {detail}. Common causes: the URL "
                f"is not public HTTPS, the codec is not H.264/AAC, the file is over the "
                f"size cap, or the aspect ratio is outside 4:5 to 1.91:1 for feed.")
        if last in {"PUBLISHED",}:
            return container_id
        time.sleep(interval)
    raise PublishError(
        f"Container {container_id} still '{last}' after {timeout}s. Meta is usually "
        f"slow on 4K video; retry the publish step, the container is valid for 24h.")


def _check_quota(client: Client) -> None:
    used, total = client.publishing_usage()
    headroom = min(total, config.LIMITS.posts_per_24h)
    if used >= total:
        raise PublishError(
            f"Publishing quota exhausted: {used}/{total} in the last 24h. Meta refuses "
            f"the next publish (code 9 / subcode 2207042). Wait for the window to roll.")
    if used >= headroom:
        store.log_metric({"event": "quota_guard", "used": used,
                          "total": total, "headroom": headroom})
        raise PublishError(
            f"Refusing to publish: {used}/{total} used, and this account's own ceiling is "
            f"{headroom} (LIMIT_POSTS_24H). A fintech account posting more than this in a "
            f"day is not a content strategy, it is a signal.")


def publish_container(client: Client, container_id: str) -> dict:
    payload = client.post(f"{client.graph.user_id}/media_publish", creation_id=container_id)
    media_id = payload.get("id")
    if not media_id:
        raise PublishError(f"media_publish returned no id: {payload}")
    return {"media_id": media_id, "container_id": container_id}


# ---------------------------------------------------------------------------
# Public shapes
# ---------------------------------------------------------------------------
def post_image(image_url: str, caption: str, *, client: Client | None = None,
               alt_text: str | None = None) -> dict:
    client = client or Client()
    _check_quota(client)
    params: dict[str, Any] = {"image_url": image_url, "caption": caption}
    if alt_text:
        params["alt_text"] = alt_text[:1000]
    container = _create_container(client, params=params, what="image")
    return publish_container(client, container)


def post_carousel(image_urls: list[str], caption: str, *,
                  client: Client | None = None) -> dict:
    if not 2 <= len(image_urls) <= 10:
        raise PublishError(f"a carousel is 2 to 10 items, got {len(image_urls)}")
    client = client or Client()
    _check_quota(client)
    children = []
    for url in image_urls:
        children.append(_create_container(
            client, params={"image_url": url, "is_carousel_item": "true"},
            what="carousel item"))
    # Items must finish before the parent is created, or the parent fails late.
    for child in children:
        _await_container(client, child, timeout=180)
    parent = _create_container(
        client,
        params={"media_type": "CAROUSEL", "children": ",".join(children),
                "caption": caption},
        what="carousel")
    return publish_container(client, parent)


def post_reel(video_url: str, caption: str, *, client: Client | None = None,
              cover_url: str | None = None, share_to_feed: bool = True,
              thumb_offset_ms: int | None = None) -> dict:
    client = client or Client()
    _check_quota(client)
    params: dict[str, Any] = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
    }
    if cover_url:
        params["cover_url"] = cover_url
    elif thumb_offset_ms is not None:
        params["thumb_offset"] = int(thumb_offset_ms)
    container = _create_container(client, params=params, what="reel")
    _await_container(client, container)
    return publish_container(client, container)


def post_story(media_url: str, *, is_video: bool, client: Client | None = None) -> dict:
    client = client or Client()
    params: dict[str, Any] = {"media_type": "STORIES",
                              "video_url" if is_video else "image_url": media_url}
    container = _create_container(client, params=params, what="story")
    if is_video:
        _await_container(client, container)
    return publish_container(client, container)


# ---------------------------------------------------------------------------
# Publish a queue item, whatever it is
# ---------------------------------------------------------------------------
def publish_item(item: dict, *, client: Client | None = None,
                 dry_run: bool = False) -> dict:
    """Take an approved queue item and put it on Instagram.

    Returns a receipt. Raises PublishError with an actionable message otherwise.
    Never publishes anything that has not been marked approved: the approval is
    the product feature, not a formality.
    """
    if item.get("status") not in {"approved", "scheduled", "publishing"}:
        raise PublishError(
            f"item {item['id']} is '{item.get('status')}', not approved. "
            f"Run `python3 -m ig approve {item['id']}` first.")
    data = item.get("data", {})
    fmt = item.get("format", "single")
    caption = data.get("caption", "")
    base = config.public_base() if not dry_run else "https://example.invalid"

    plan = []
    if fmt in {"reel", "video"}:
        video = data.get("video_path") or data.get("video_url")
        if not video:
            raise PublishError(f"item {item['id']} is a reel with no video_path")
        url = video if str(video).startswith("http") else _public_url(video, base)
        plan.append(("post_reel", {"video_url": url, "caption": caption,
                                   "cover_url": _public_url(data["cover_path"], base)
                                   if data.get("cover_path") else None}))
    elif fmt == "carousel":
        slides = data.get("slide_paths") or []
        if len(slides) < 2:
            raise PublishError(f"item {item['id']} says carousel but has {len(slides)} slides")
        plan.append(("post_carousel", {"image_urls": [_public_url(s, base) for s in slides],
                                       "caption": caption}))
    elif fmt == "story":
        media = data.get("video_path") or data.get("image_path")
        if not media:
            raise PublishError(f"item {item['id']} is a story with no media")
        is_video = str(media).lower().endswith((".mp4", ".mov", ".m4v"))
        plan.append(("post_story", {"media_url": _public_url(media, base),
                                    "is_video": is_video}))
    else:
        image = data.get("image_path") or data.get("image_url")
        if not image:
            raise PublishError(f"item {item['id']} is a single image post with no image")
        url = image if str(image).startswith("http") else _public_url(image, base)
        plan.append(("post_image", {"image_url": url, "caption": caption,
                                    "alt_text": data.get("alt_text")}))

    if dry_run:
        return {"dry_run": True, "format": fmt, "planned_calls": [name for name, _ in plan]}

    client = client or Client()
    store.update_item(item["id"], status="publishing")
    try:
        fn_name, kwargs = plan[0]
        fn = {"post_reel": post_reel, "post_carousel": post_carousel,
              "post_image": post_image, "post_story": post_story}[fn_name]
        result = fn(client=client, **kwargs)
    except Exception as exc:
        store.update_item(item["id"], status="failed", error=str(exc))
        raise
    receipt = {
        "item_id": item["id"],
        "format": fmt,
        "media_id": result["media_id"],
        "container_id": result.get("container_id"),
        "published_at": store._now(),
        "published_at_epoch": time.time(),
        "caption_preview": caption[:120],
        "permalink": _permalink(client, result["media_id"]),
    }
    store.update_item(item["id"], status="published", media_id=result["media_id"],
                      permalink=receipt["permalink"])
    store.log_posted(receipt)
    return receipt


def _public_url(path: str, base: str) -> str:
    """Turn build/publish/x.jpg into https://<public-base>/x.jpg.

    Only files inside build/publish are addressable, because a public base
    pointing at a directory is a public file listing: brand voice notes and
    client numbers must not end up there.
    """
    p = Path(path)
    try:
        rel = p.resolve().relative_to(config.PUBLISH_DIR.resolve())
    except ValueError:
        raise PublishError(
            f"{path} is not under {config.PUBLISH_DIR}. Copy it there (or render into "
            f"it) before publishing: anything else is not served by "
            f"PUBLIC_MEDIA_BASE_URL.") from None
    return f"{base}/{rel.as_posix()}"


def _permalink(client: Client, media_id: str) -> str | None:
    try:
        return client.get(media_id, fields="permalink").get("permalink")
    except GraphError:
        return None


# ---------------------------------------------------------------------------
# What is already live: the only reliable source of "did we post today"
# ---------------------------------------------------------------------------
def recent_media(client: Client | None = None, limit: int = 12) -> list[dict]:
    client = client or Client()
    payload = client.get(
        f"{client.graph.user_id}/media",
        fields="id,caption,media_type,media_product_type,permalink,timestamp,"
               "like_count,comments_count",
        limit=limit)
    return payload.get("data", [])
