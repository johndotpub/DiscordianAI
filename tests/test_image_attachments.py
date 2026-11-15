"""Unit tests for Discord image attachment validation and decoding."""

import base64
from unittest.mock import AsyncMock

import pytest

from src.image_attachments import ImagePayload, extract_images, sniff_image_mime

PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
JPEG = b"\xff\xd8\xff" + b"jpeg-body"
GIF = b"GIF89a" + b"gif-body"
WEBP = b"RIFF\x10\x00\x00\x00WEBP" + b"webp-body"


class FakeAttachment:
    """Minimal Discord attachment double with a configurable read result."""

    def __init__(  # noqa: PLR0913 - mirrors the Discord attachment fields under test
        self,
        data=b"",
        *,
        filename="image.png",
        content_type="image/png",
        size=None,
        width=None,
        height=None,
        error=None,
    ):
        self.filename = filename
        self.content_type = content_type
        self.size = len(data) if size is None else size
        self.width = width
        self.height = height
        self._data = data
        self._error = error
        self.read = AsyncMock(side_effect=self._read)

    async def _read(self):
        if self._error is not None:
            raise self._error
        return self._data


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (WEBP, "image/webp"),
    ],
)
def test_magic_bytes_sniff_each_supported_format(data, expected):
    assert sniff_image_mime(data) == expected


def test_missing_content_type_uses_magic_bytes():
    attachment = FakeAttachment(PNG, content_type=None, width=8, height=8)

    images, skipped = _run(extract_images([attachment]))

    assert skipped == []
    assert len(images) == 1
    assert images[0].mime == "image/png"
    assert (images[0].width, images[0].height) == (8, 8)


def test_generic_content_type_uses_magic_bytes():
    attachment = FakeAttachment(JPEG, content_type="application/octet-stream")

    images, skipped = _run(extract_images([attachment]))

    assert skipped == []
    assert images[0].mime == "image/jpeg"


def test_declared_image_mime_is_accepted_without_sniffing():
    attachment = FakeAttachment(b"not-really-a-png", content_type="image/png")

    images, skipped = _run(extract_images([attachment]))

    assert skipped == []
    assert images[0].mime == "image/png"


def test_unknown_bytes_are_skipped_with_a_reason():
    attachment = FakeAttachment(b"plain text", content_type=None, filename="notes.txt")

    images, skipped = _run(extract_images([attachment]))

    assert images == []
    assert skipped == ["unsupported_type: notes.txt"]


def test_non_image_content_type_is_skipped_before_read():
    attachment = FakeAttachment(b"hello", content_type="text/plain")

    images, skipped = _run(extract_images([attachment]))

    assert images == []
    assert skipped == ["unsupported_type: image.png"]
    attachment.read.assert_not_awaited()


def test_oversize_declared_size_is_skipped_before_download():
    attachment = FakeAttachment(PNG, size=11, filename="big.png")

    images, skipped = _run(extract_images([attachment], max_bytes=10))

    assert images == []
    assert skipped == ["oversize_before_download: big.png (11 bytes)"]
    attachment.read.assert_not_awaited()


def test_oversize_after_download_is_skipped():
    attachment = FakeAttachment(PNG, size=1, filename="liar.png")

    images, skipped = _run(extract_images([attachment], max_bytes=4))

    assert images == []
    assert skipped == [f"oversize_after_download: liar.png ({len(PNG)} bytes)"]


def test_max_count_accepts_only_the_first_images():
    attachments = [FakeAttachment(PNG, filename=f"one-{index}.png") for index in range(3)]

    images, skipped = _run(extract_images(attachments, max_count=2))

    assert [image.filename for image in images] == ["one-0.png", "one-1.png"]
    assert skipped == ["too_many_images: one-2.png"]


def test_zero_max_count_skips_every_attachment():
    attachment = FakeAttachment(PNG, filename="one.png")

    images, skipped = _run(extract_images([attachment], max_count=0))

    assert images == []
    assert skipped == ["too_many_images: one.png"]
    attachment.read.assert_not_awaited()


def test_read_failure_does_not_drop_the_other_images():
    failing = FakeAttachment(error=OSError("cdn down"), filename="bad.png")
    good = FakeAttachment(GIF, filename="good.gif", content_type=None)

    images, skipped = _run(extract_images([failing, good]))

    assert [image.filename for image in images] == ["good.gif"]
    assert skipped == ["read_failed: bad.png (OSError)"]


def test_payload_base64_round_trips_and_skips_do_not_echo_bytes():
    attachment = FakeAttachment(WEBP, content_type=None, filename="pic.webp")

    images, skipped = _run(extract_images([attachment]))

    assert skipped == []
    payload = images[0]
    assert isinstance(payload, ImagePayload)
    assert base64.b64decode(payload.data_b64) == WEBP
    assert "WEBP" not in skipped


def test_empty_attachment_list_returns_no_images():
    images, skipped = _run(extract_images([]))

    assert images == []
    assert skipped == []


def _run(awaitable):
    """Run one extract_images coroutine without a shared event-loop marker."""

    import asyncio

    return asyncio.run(awaitable)
