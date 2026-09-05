from pathlib import Path

import config
from routes.images import _MEDIA_TYPES
from tests.test_scanner import get_image, run_scan


def test_jfif_avif_mp4_mov_are_supported_extensions():
    for ext in (".jfif", ".avif", ".mp4", ".mov"):
        assert ext in config.SUPPORTED_IMAGE_FORMATS


def test_avif_and_mov_have_explicit_media_types():
    """Regression: Python's mimetypes module doesn't know .avif, so
    FileResponse would otherwise send a wrong/missing Content-Type."""
    assert _MEDIA_TYPES[".avif"] == "image/avif"
    assert _MEDIA_TYPES[".mov"] == "video/quicktime"
    assert _MEDIA_TYPES[".mp4"] == "video/mp4"


async def test_video_files_are_scanned_with_null_dimensions(db, tmp_path):
    """Catalog-only support: a video file gets scanned and hashed like any
    other file, but PIL can't open it so dimensions stay NULL -- same
    fallback path as any other unreadable file, no special-casing needed."""
    video = tmp_path / "characters" / "game" / "char" / "clip.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"not a real mp4, just bytes for hashing")

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, video)
    assert row is not None
    assert row["image_width"] is None
    assert row["image_height"] is None
    assert row["file_hash"] is not None
