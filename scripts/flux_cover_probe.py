#!/usr/bin/env python3
"""Manual-only, bounded Cloudflare Workers AI cover experiment (HPI).

Exactly 3 requests to @cf/black-forest-labs/flux-2-klein-4b, 1024x576 each.
Uses a Cloudflare Workers FREE account, not AI Gateway or paid model fallback.
Outputs local preview PNGs + contact sheet; never updates published site content.
"""
import base64
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_test_output" / "flux"
MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
WIDTH, HEIGHT = 1024, 576
TITLE = "ССЫЛКИ НА ВИДУ"
SUBTITLE = "Google меняет ИИ-поиск"

# Same factual story, deliberately contrasting visual treatments.
CONCEPTS = [
    {
        "file": "01_poster",
        "style": "Европейский концептуальный плакат",
        "background": "#111e32",
        "prompt": (
            "Landscape 16:9 sophisticated European conceptual illustration, "
            "Swiss editorial poster influence, bold clean shapes, 3 ink colors: "
            "deep cobalt, off-white and vermilion. A huge magnifying glass lifts "
            "a small stack of source documents into view from a geometric search "
            "results labyrinth. Inventive visual metaphor, balanced negative space, "
            "subtle printing grain but no pixel noise, no technology clichés. "
            "NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO LOGOS, NO WATERMARKS. "
            "Clear lower quarter for typography added separately."
        ),
    },
    {
        "file": "02_cinema",
        "style": "Кинематографическая иллюстрация",
        "background": "#182522",
        "prompt": (
            "Widescreen 16:9 cinematic art-directed illustration, a detective "
            "archive room at dusk, person seen from behind illuminating the "
            "original source cards hidden behind oversized opaque AI-search "
            "answer panels on a desk, strong storytelling composition, dramatic "
            "amber desk lamp, moss green shadows, tactile painted surfaces, "
            "unexpected intimate film still, NOT photo-realistic. "
            "NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO LOGOS, NO WATERMARKS. "
            "Composition with simple dark lower quarter for later text overlay."
        ),
    },
    {
        "file": "03_surreal",
        "style": "Художественный сюрреализм",
        "background": "#2b1e27",
        "prompt": (
            "Widescreen 16:9 poetic painterly surrealist editorial artwork: "
            "an enormous folded search-results paper mountain, windows cut "
            "through paper revealing vibrant real landscapes beyond; a tiny "
            "traveler pushes open one small window, surreal visual allegory "
            "of links to original sources becoming more visible. Rich coral, "
            "indigo, dusty turquoise, unusual sculptural perspective, "
            "premium tactile brushwork, clean readable composition. "
            "NO TEXT, NO LETTERS, NO TYPOGRAPHY, NO LOGOS, NO WATERMARKS. "
            "Keep lower quarter relatively calm for later text overlay."
        ),
    },
]


def multipart_fields(fields):
    """Build Cloudflare's required multipart/form-data with generated boundary."""
    boundary = "hpi-" + uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        if not re.fullmatch(r"[a-zA-Z0-9_]+", key):
            raise ValueError("Invalid multipart field name")
        body.extend(("--" + boundary + "\r\n").encode())
        body.extend(('Content-Disposition: form-data; name="' + key + '"\r\n\r\n').encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(("--" + boundary + "--\r\n").encode())
    return bytes(body), "multipart/form-data; boundary=" + boundary


def image_from_response(body, content_type):
    """Cloudflare model returns result.image as base64, sometimes a direct PNG."""
    if body.startswith(b"\x89PNG\r\n\x1a\n") or body.startswith(b"\xff\xd8\xff"):
        return body
    if "json" not in content_type.lower() and not body.lstrip().startswith(b"{"):
        raise RuntimeError("Unexpected Cloudflare response content type")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise RuntimeError("Invalid Cloudflare JSON response") from None
    if not isinstance(message, dict) or message.get("success") is False:
        raise RuntimeError("Cloudflare indicated inference failure")
    result = message.get("result")
    if isinstance(result, dict):
        encoded = result.get("image")
    else:
        encoded = message.get("image")
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Cloudflare returned no base64 image")
    if encoded.startswith("data:image/"):
        encoded = encoded.split(",", 1)[-1]
    try:
        result_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        raise RuntimeError("Cloudflare returned invalid image base64") from None
    if not (result_bytes.startswith(b"\x89PNG\r\n\x1a\n") or result_bytes.startswith(b"\xff\xd8\xff")):
        raise RuntimeError("Cloudflare returned data that is not PNG/JPEG")
    return result_bytes


def generate(account_id, token, prompt):
    if not re.fullmatch(r"[0-9a-fA-F]{32}", account_id):
        raise RuntimeError("Cloudflare Account ID is missing or malformed (expect 32 hex characters)")
    if not token or len(token) < 16:
        raise RuntimeError("Missing Cloudflare API token")
    endpoint = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + account_id + "/ai/run/" + MODEL
    )
    body, mimetype = multipart_fields({
        "prompt": prompt, "width": WIDTH, "height": HEIGHT,
    })
    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": mimetype,
            "Accept": "application/json",
            "User-Agent": "HPI-FLUX-Free-Probe/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=100) as res:
            raw = res.read(18 * 1024 * 1024 + 1)
            if len(raw) > 18 * 1024 * 1024:
                raise RuntimeError("Cloudflare image response unusually large")
            if res.status != 200:
                raise RuntimeError("Cloudflare HTTP " + str(res.status))
            return image_from_response(raw, res.headers.get("Content-Type", "application/json"))
    except urllib.error.HTTPError as exc:
        # Never dump URLs, headers, body, account ID, token or raw API errors.
        hints = {401: "invalid API token", 403: "model/account permission or plan denied",
                 404: "model endpoint unavailable", 413: "payload too large",
                 429: "free quota or rate limit exceeded"}
        raise RuntimeError("Cloudflare HTTP " + str(exc.code) + ": " +
                           hints.get(exc.code, "request rejected")) from None
    except urllib.error.URLError:
        raise RuntimeError("Cloudflare network request failed") from None


def make_cover(raw_bytes, concept, title=None, subtitle=None):
    title = (title or TITLE).strip()
    subtitle = (subtitle or SUBTITLE).strip()
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    with Image.open(io.BytesIO(raw_bytes)) as input_image:
        input_image.load()
        if input_image.width < 256 or input_image.height < 256:
            raise RuntimeError("Cloudflare image dimensions are unexpectedly small")
        image = ImageOps.fit(input_image.convert("RGB"), (WIDTH, HEIGHT),
                            method=Image.Resampling.LANCZOS)
    image = image.convert("RGBA")
    glaze = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(glaze)
    # A progressive dark band keeps Cyrillic lettering legible, regardless of
    # what the external generative model drew. No AI image text needed.
    for y in range(352, HEIGHT):
        alpha = round(218 * (y - 352) / (HEIGHT - 352))
        draw.line((0, y, WIDTH, y), fill=(13, 17, 27, alpha))
    draw.rounded_rectangle((32, 27, 345, 70), radius=13, fill=(12, 16, 24, 196))
    image = Image.alpha_composite(image, glaze)
    d = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not Path(font_path).exists() or not Path(font_regular).exists():
        raise RuntimeError("Cyrillic DejaVu fonts not available on GitHub runner")
    font_brand = ImageFont.truetype(font_path, 17)
    # Shrink to width; news headlines vary from one draft to the next.
    font_size = 67
    font_title = ImageFont.truetype(font_path, font_size)
    while d.textbbox((0, 0), title, font=font_title)[2] > WIDTH - 90 and font_size > 32:
        font_size -= 2
        font_title = ImageFont.truetype(font_path, font_size)
    font_subtitle = ImageFont.truetype(font_regular, 27)
    d.text((47, 36), "ХРОНИКИ ПИКИРУЮЩЕГО ИИ", font=font_brand, fill="white")
    d.text((44, 411), title, font=font_title, fill="white",
           stroke_width=1, stroke_fill=(14, 18, 28))
    d.text((47, 502), subtitle, font=font_subtitle, fill="#e6e6e6")
    return image.convert("RGB")


def main():
    key = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not key or not account:
        raise RuntimeError("Missing CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID GitHub secret")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    meta = []
    for concept in CONCEPTS:
        # Fixed number of calls, no retries, no alternate/premium models.
        raw = generate(account, key, concept["prompt"])
        image = make_cover(raw, concept)
        name = concept["file"] + ".png"
        image.save(OUTPUT / name, format="PNG", optimize=True)
        meta.append({"image": name, "style": concept["style"],
                     "model": MODEL, "dimensions": [WIDTH, HEIGHT]})
        print("Generated draft cover: " + name, flush=True)
    (OUTPUT / "manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Side by side contact sheet for comparison, no social publishing.
    from PIL import Image, ImageDraw, ImageFont
    contact = Image.new("RGB", (WIDTH, HEIGHT * len(meta)), "#11151e")
    for i, item in enumerate(meta):
        with Image.open(OUTPUT / item["image"]) as cover:
            contact.paste(cover, (0, HEIGHT * i))
    contact.save(OUTPUT / "comparison.jpg", quality=88, optimize=True)
    print("Three private preview images and comparison sheet saved.", flush=True)
    print("NO site or social platform files were changed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FLUX PROBE ERROR: " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
