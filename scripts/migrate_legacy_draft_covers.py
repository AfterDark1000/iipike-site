#!/usr/bin/env python3
"""Safely migrate legacy /drafts/<id>/cover.png previews to WebP in a review branch.

This script never touches production assets/editorial, editorial_inbox, news.json,
published articles, site queue or Git history. Mode --check is read-only.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
from PIL import Image, UnidentifiedImageError

ID = re.compile(r"[0-9a-f]{20}\Z")


def compress(original: Path) -> bytes:
    try:
        with Image.open(original) as image:
            if image.format != "PNG":
                raise ValueError("Legacy preview is not a PNG")
            image.load()
            if image.width < 640 or image.height < 360 or abs(image.width/image.height-16/9) > .03:
                raise ValueError("Legacy preview aspect ratio/dimensions invalid")
            rgb=image.convert("RGB")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("Cannot read legacy PNG " + original.name) from error
    for quality in (84,80,76,72):
        data=BytesIO()
        rgb.save(data,"WEBP",quality=quality,method=6)
        result=data.getvalue()
        if len(result) <= 800_000:
            with Image.open(BytesIO(result)) as test:
                if test.format != "WEBP" or test.size != rgb.size:
                    raise ValueError("Failed WebP roundtrip")
                test.load()
            return result
    raise ValueError("Conversion remained larger than 800 KB")


def plan(root: Path):
    shelf=root/"drafts"
    catalog=json.loads((shelf/"index.json").read_text(encoding="utf-8"))
    if not isinstance(catalog,list) or any(not isinstance(row,dict) or
        not isinstance(row.get("id"),str) or not ID.fullmatch(row["id"]) for row in catalog):
        raise ValueError("Invalid preview catalog")
    ids=[row["id"] for row in catalog]
    if len(ids)!=len(set(ids)):
        raise ValueError("Duplicate preview IDs")
    listing=shelf/"index.html"
    index=listing.read_text(encoding="utf-8")
    candidates=[]
    for id in ids:
        directory=shelf/id
        png=directory/"cover.png"
        webp=directory/"cover.webp"
        html=directory/"index.html"
        if not png.is_file(): continue
        if webp.exists(): raise ValueError("Refusing to overwrite already existing WebP: "+id)
        page=html.read_text(encoding="utf-8")
        if page.count('src="cover.png"')!=1 or index.count(id+'/cover.png')!=1:
            raise ValueError("Legacy PNG references unexpected: "+id)
        converted=compress(png)
        candidates.append((id,png,webp,html,page,converted))
    catalog_png=set(id for id,_,_,_,_,_ in candidates)
    stray=[path for path in shelf.glob("*/cover.png") if path.parent.name not in catalog_png]
    if stray:
        raise ValueError("Uncatalogued PNG present; refusing partial cleanup")
    # Verify ALL data and page references before writing/removing any file.
    planned=index
    for id, *_ in candidates:
        planned=planned.replace(id+"/cover.png", id+"/cover.webp")
    return candidates, listing, planned


def migrate(root: Path, apply: bool=False):
    candidates,listing,index=plan(root)
    before=sum(c[1].stat().st_size for c in candidates)
    after=sum(len(c[-1]) for c in candidates)
    if apply and candidates:
        # Write optimized files and update references before removing PNGs.
        for id,png,webp,html,page,data in candidates:
            webp.write_bytes(data)
            html.write_text(page.replace('src="cover.png"','src="cover.webp"'),encoding="utf-8")
        listing.write_text(index,encoding="utf-8")
        for _,png,*_ in candidates:
            png.unlink()
        # All original links changed; no stale src paths to missing assets.
        assert not any((root/"drafts"/id/"cover.png").exists() for id,*_ in candidates)
    print(f"Legacy previews: {len(candidates)} files; original {before} bytes, "
          f"WebP {after} bytes; estimated active-tree saving {before-after} bytes; "
          f"mode={'applied' if apply else 'check only'}")
    return len(candidates),before,after


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",help="Convert and update draft pages in this checkout")
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    migrate(args.root,args.apply)
