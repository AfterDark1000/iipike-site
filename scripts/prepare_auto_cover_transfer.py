#!/usr/bin/env python3
"""Prepare a genuine ChatGPT Images cover for the GitHub base64 blob bridge.

Does not connect to GitHub or publish anything. The .b64 output is temporary
transfer data, NEVER an editorial_inbox/auto_covers candidate.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
from pathlib import Path
from PIL import Image, ImageOps

SIZE = (1600, 900)
MAX_BYTES = 800_000
QUALITIES = (86, 82, 78, 74, 70, 65, 60, 55)


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def prepare(source: Path, target_dir: Path, stem: str) -> dict:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-r[1-9][0-9]*-v[1-5]", stem):
        raise ValueError("Cover stem must be <article_id>-r<revision>-v<1..5>")
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size > 20_000_000:
        raise ValueError("Image source is unexpectedly large")
    with Image.open(source) as im:
        im.load()
        if im.width < 640 or im.height < 360 or abs(im.width / im.height - 16 / 9) > 0.03:
            raise ValueError("Source must be a real horizontal 16:9 image at least 640x360")
        img = ImageOps.fit(im.convert("RGB"), SIZE, method=Image.Resampling.LANCZOS)
    chosen = None
    for quality in QUALITIES:
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=6)
        if len(buf.getvalue()) <= MAX_BYTES:
            chosen = buf.getvalue()
            break
    if chosen is None:
        raise ValueError("No WebP version fits 800 KB limit")
    with Image.open(io.BytesIO(chosen)) as verified:
        verified.load()
        if verified.format != "WEBP" or verified.size != SIZE:
            raise AssertionError("Encoded image failed WebP decoder or size check")
    if chosen[:4] != b"RIFF" or chosen[8:12] != b"WEBP" or len(chosen) < 1024:
        raise ValueError("Not a valid reasonably sized WebP binary")
    target_dir.mkdir(parents=True, exist_ok=True)
    webp = target_dir / f"{stem}.webp"
    b64 = target_dir / f"{stem}.webp.b64"
    manifest = target_dir / f"{stem}.transfer.json"
    if any(x.exists() for x in (webp, b64, manifest)):
        raise FileExistsError("Transfer output exists; refusing to overwrite")
    encoded = base64.b64encode(chosen).decode("ascii")
    # Files.read can retrieve this text by bounded line ranges.
    lines = [encoded[i:i + 512] for i in range(0, len(encoded), 512)]
    info = {
        "format": "webp",
        "stem": stem,
        "image_bytes": len(chosen),
        "width": SIZE[0],
        "height": SIZE[1],
        "git_blob_sha": blob_sha(chosen),
        "sha256": hashlib.sha256(chosen).hexdigest(),
        "base64_chars": len(encoded),
        "base64_line_count": len(lines),
    }
    webp.write_bytes(chosen)
    b64.write_text("\n".join(lines) + "\n", encoding="ascii")
    manifest.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="actual image from ChatGPT Images")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--stem", required=True)
    args = parser.parse_args()
    info = prepare(args.source, args.out_dir, args.stem)
    print("TRANSFER_READY " + json.dumps(info, ensure_ascii=False))
    print("This is NOT a saved GitHub cover. Continue via verified GitHub blob + commit.")


if __name__ == "__main__":
    main()
