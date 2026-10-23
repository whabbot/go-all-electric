"""Strip image metadata before any Gemini call. Uploads stay in memory only."""

from io import BytesIO

from PIL import Image, ImageOps

# Re-encode cap keeps inline payloads predictable; frontend uses the same max edge.
_MAX_EDGE_PX = 2048
_JPEG_QUALITY = 88


def sanitize_image(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """Drop EXIF/GPS and other metadata; return JPEG bytes."""
    if not mime_type.startswith("image/"):
        return data, mime_type
    try:
        with Image.open(BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, _MAX_EDGE_PX / max(w, h))
            if scale < 1.0:
                im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            out = BytesIO()
            im.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception:
        # Unreadable image: pass through; Gemini route will fail legibly.
        return data, mime_type
