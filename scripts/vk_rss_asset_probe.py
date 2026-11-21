#!/usr/bin/env python3
"""Read-only truth about real WebP/JPEG dimensions for the VK RSS investigation."""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IDS = [
    "anthropic-record-ipo-81b-nasdaq-20261119",
    "bitdefender-github-agent-instructions-malware-20261117",
    "nvidia-china-hopper-shipments-halt-20261118",
    "meta-muse-chrome-login-20261120",
]

def main():
    rows = {r["id"]: r for r in json.loads((ROOT / "news.json").read_text(encoding="utf-8"))}
    for slug in IDS:
        source = ROOT / rows[slug]["cover"]
        jpeg = ROOT / "assets" / "vk" / (slug + ".jpg")
        if not source.is_file() or not jpeg.is_file():
            raise ValueError("Missing real image: " + slug)
        with Image.open(source) as original, Image.open(jpeg) as vk:
            source_size = original.size
            image_size = vk.size
            if vk.format != "JPEG":
                raise ValueError("VK image is not JPEG: " + slug)
            if image_size[0] > source_size[0] or image_size[1] > source_size[1]:
                raise ValueError("VK export unexpectedly enlarged original: " + slug)
            print("VK IMAGE DIMENSIONS:", slug,
                  "SOURCE", f"{source_size[0]}x{source_size[1]}",
                  "JPEG", f"{image_size[0]}x{image_size[1]}",
                  "source_bytes", source.stat().st_size,
                  "jpg_bytes", jpeg.stat().st_size,
                  "source_below_1280x720", source_size[0] < 1280 or source_size[1] < 720)

if __name__ == "__main__":
    main()
