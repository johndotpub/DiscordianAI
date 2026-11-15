"""Extraction of Discord image attachments into provider-ready payloads.

The module owns the attachment policy: which MIME types are accepted, how large
one image may be, how many images one message may carry, and how a declared
content type is verified against the bytes Discord served. It never fetches any
URL other than the attachment that Discord already handed the bot.
"""

import base64
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .config import (
    DEFAULT_VISION_MAX_BYTES,
    DEFAULT_VISION_MAX_IMAGES,
)

ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

_GENERIC_CONTENT_TYPES = frozenset(
    {
        "",
        "application/octet-stream",
        "binary/octet-stream",
        "unknown",
    }
)

_MAGIC_PREFIXES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_WEBP_HEADER_LENGTH = 12


@dataclass(frozen=True)
class ImagePayload:
    """One validated image attachment ready for a chat request.

    ``data_b64`` carries the base64-encoded image bytes and is never logged.
    ``width`` and ``height`` stay ``None`` when Discord did not report them.
    """

    filename: str
    mime: str
    data_b64: str
    width: int | None = None
    height: int | None = None


def sniff_image_mime(data: bytes | bytearray | memoryview) -> str | None:
    """Return the image MIME type implied by leading magic bytes.

    Args:
        data: Raw attachment bytes.

    Returns:
        One of the accepted image MIME types, or ``None`` when the bytes do not
        match a supported format.
    """
    raw = bytes(data or b"")
    for prefix, mime in _MAGIC_PREFIXES:
        if raw.startswith(prefix):
            return mime
    if (
        len(raw) >= _WEBP_HEADER_LENGTH
        and raw[:4] == b"RIFF"
        and raw[8:_WEBP_HEADER_LENGTH] == b"WEBP"
    ):
        return "image/webp"
    return None


def _filename(attachment: Any) -> str:
    """Return a short attachment filename for logs and skip reasons."""
    value = getattr(attachment, "filename", "") or ""
    return str(value)[:200]


def _label(filename: str) -> str:
    """Return a human-readable name for an attachment without a filename."""
    return filename or "<unnamed>"


def _declared_mime(attachment: Any) -> str | None:
    """Return the normalised declared content type, if one was supplied."""
    value = getattr(attachment, "content_type", None)
    if not value:
        return None
    declared = str(value).split(";", 1)[0].strip().lower()
    return declared or None


def _declared_size(attachment: Any) -> int | None:
    """Return the declared attachment size in bytes, when Discord supplied it."""
    value = getattr(attachment, "size", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pixel_dimension(attachment: Any, name: str) -> int | None:
    """Return an optional integer width or height from an attachment."""
    value = getattr(attachment, name, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def extract_images(
    attachments: Iterable[Any] | None,
    *,
    max_bytes: int = DEFAULT_VISION_MAX_BYTES,
    max_count: int = DEFAULT_VISION_MAX_IMAGES,
) -> tuple[list[ImagePayload], list[str]]:
    """Validate and download image attachments for one Discord message.

    Each attachment is handled independently: a rejected or failed attachment
    is recorded in ``skipped_reasons`` and never aborts the message. Accepted
    images are capped by ``max_count`` and ``max_bytes`` both before and after
    the Discord download.

    Args:
        attachments: Discord attachment objects exposing ``filename``,
            ``content_type``, ``size``, and an awaitable ``read()``.
        max_bytes: Maximum accepted size for one image in bytes.
        max_count: Maximum number of images accepted from one message.

    Returns:
        A tuple ``(images, skipped_reasons)``. ``skipped_reasons`` contains one
        short, non-secret line per rejected attachment.
    """
    images: list[ImagePayload] = []
    skipped: list[str] = []
    byte_limit = int(max_bytes)
    count_limit = max(0, int(max_count))

    for attachment in attachments or ():
        filename = _filename(attachment)
        label = _label(filename)

        if len(images) >= count_limit:
            skipped.append(f"too_many_images: {label}")
            continue

        declared = _declared_mime(attachment)
        if (
            declared is not None
            and declared not in ALLOWED_IMAGE_MIME_TYPES
            and declared not in _GENERIC_CONTENT_TYPES
        ):
            skipped.append(f"unsupported_type: {label}")
            continue

        declared_size = _declared_size(attachment)
        if declared_size is not None and declared_size > byte_limit:
            skipped.append(f"oversize_before_download: {label} ({declared_size} bytes)")
            continue

        try:
            raw = await attachment.read()
        except Exception as exc:  # noqa: BLE001 - one failed attachment must not drop the message
            skipped.append(f"read_failed: {label} ({type(exc).__name__})")
            continue

        if not isinstance(raw, (bytes, bytearray, memoryview)):
            skipped.append(f"invalid_payload: {label}")
            continue

        data = bytes(raw)
        if not data:
            skipped.append(f"empty_file: {label}")
            continue
        if len(data) > byte_limit:
            skipped.append(f"oversize_after_download: {label} ({len(data)} bytes)")
            continue

        detected = sniff_image_mime(data)
        if detected is None:
            skipped.append(f"unsupported_type: {label}")
            continue

        if declared in ALLOWED_IMAGE_MIME_TYPES and declared != detected:
            skipped.append(f"mime_mismatch: {label} (declared {declared}, detected {detected})")
            continue

        images.append(
            ImagePayload(
                filename=filename,
                mime=detected,
                data_b64=base64.b64encode(data).decode("ascii"),
                width=_pixel_dimension(attachment, "width"),
                height=_pixel_dimension(attachment, "height"),
            )
        )

    return images, skipped
