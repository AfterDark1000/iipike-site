#!/usr/bin/env python3
"""HPII autonomous cover candidate worker: one owner-approved text -> one WebP.

Generation uses only the existing explicitly configured Cloudflare Workers AI FLUX
model, never a paid fallback. No article/social publication and no approval writes.
The worker is run from main; --root points to an editorial-intake worktree.
"""
import argparse
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scripts import flux_cover_probe
from scripts.check_auto_cover_pilot import git_blob_sha, validate as validate_cover

STYLES = (
    {
        "name": "Сатирическая книжная линогравюра",
        "art": "Satirical 1960s editorial linocut and torn-paper collage, uneven print registration, warm paper grain, expressive characters, forest green, ochre, dusty rose and black ink. Strong storytelling, humorous without infantilizing.",
        "background": (18, 55, 47, 248),
        "foreground": (255, 244, 215),
        "layout": "left",
    },
    {
        "name": "Кинематографическая живопись",
        "art": "Sophisticated cinematic gouache illustration, diagonal perspective, earthy indigo shadows and dramatic amber practical lighting, atmospheric detail, no stock-photo language.",
        "background": (30, 31, 45, 244),
        "foreground": (250, 241, 212),
        "layout": "bottom",
    },
    {
        "name": "Европейский сюрреалистический плакат",
        "art": "Poetic surrealist European art poster, oversized visual metaphor, tactile brushwork, elegant negative space, dusty violet, tobacco brown and pale turquoise palette.",
        "background": (51, 35, 59, 244),
        "foreground": (255, 240, 207),
        "layout": "right",
    },
    {
        "name": "Газетный сатирический комикс",
        "art": "Hand-inked satirical newspaper comic, expressive panel-free storytelling, witty visual staging, warm halftone texture, limited navy, red-orange and cream inks.",
        "background": (16, 43, 65, 250),
        "foreground": (255, 247, 219),
        "layout": "left",
    },
    {
        "name": "Живописная обложка книги",
        "art": "Painterly contemporary European book-cover illustration, surprising symbolism, visible brush strokes, restrained moss green and rust palette with tactile paper.",
        "background": (55, 41, 37, 245),
        "foreground": (253, 238, 211),
        "layout": "bottom",
    },
    {
        "name": "Графический конструктивистский коллаж",
        "art": "Original graphic print collage, striking asymmetric framing, angular paper-cut shapes, vivid mustard, dark plum and muted jade, tactile imperfect printing.",
        "background": (46, 28, 53, 246),
        "foreground": (255, 239, 207),
        "layout": "right",
    },
)
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
MIN_WIDTH, MIN_HEIGHT = 1600, 900


def safe_doc(path):
    return json.loads(path.read_text(encoding="utf-8"))


def eligible(root):
    """Return oldest fully approved text with no first cover candidate."""
    inbox = root / "editorial_inbox"
    found = []
    for path in sorted((inbox / "auto_drafts").glob("*.json")):
        if path.name == "README.md":
            continue
        try:
            draft_bytes = path.read_bytes()
            draft = json.loads(draft_bytes)
            if draft.get("status") != "ready_for_review":
                continue
            article_id = draft.get("article_id")
            revision = draft.get("revision")
            if not isinstance(article_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", article_id):
                continue
            if type(revision) is not int or revision < 1 or path.stem != article_id:
                continue
            decision_path = inbox / "auto_decisions" / f"{article_id}-r{revision}.json"
            if not decision_path.is_file():
                continue
            decision_bytes = decision_path.read_bytes()
            decision = json.loads(decision_bytes)
            if (decision.get("action") != "approve_text" or
                    decision.get("status") != "text_approved_cover_pending" or
                    decision.get("article_id") != article_id or
                    decision.get("revision") != revision or
                    decision.get("updated_at") != draft.get("updated_at") or
                    decision.get("draft_blob_sha") != git_blob_sha(draft_bytes)):
                continue
            stem = f"{article_id}-r{revision}-v1"
            covers_dir = inbox / "auto_covers"
            if (covers_dir / (stem + ".webp")).exists() or (covers_dir / (stem + ".json")).exists():
                continue
            if (inbox / "auto_cover_decisions" / (stem + ".json")).exists():
                continue
            if (inbox / "auto_handoffs" / (stem + ".json")).exists():
                continue
            if not isinstance(draft.get("content"), dict) or not isinstance(draft.get("cover_brief"), dict):
                continue
            if not draft["content"].get("title") or not draft["cover_brief"].get("fact"):
                continue
            found.append((decision.get("decided_at", "9999"), draft.get("pool_sequence", 999999),
                          article_id, revision, draft, decision, draft_bytes, decision_bytes))
        except (ValueError, OSError, TypeError, KeyError):
            # Broken candidates are not approved. Other healthy work can proceed.
            continue
    if not found:
        return None
    found.sort(key=lambda x: (x[0], x[1], x[2]))
    _, _, article_id, revision, draft, decision, draft_bytes, decision_bytes = found[0]
    brief = draft["cover_brief"]
    style_index = int(hashlib.sha256(article_id.encode()).hexdigest()[:8], 16) % len(STYLES)
    if "кроссовк" in (brief["fact"] + " " + brief.get("hook", "")).lower():
        style_index = 0
    snippet = re.search(r"«([^»]{12,72})»", brief.get("constraints", ""))
    headline = snippet.group(1) if snippet else draft["content"]["title"]
    return {
        "article_id": article_id,
        "revision": revision,
        "updated_at": draft["updated_at"],
        "draft_sha": git_blob_sha(draft_bytes),
        "decision_sha": git_blob_sha(decision_bytes),
        "image_path": "editorial_inbox/auto_covers/" + article_id + f"-r{revision}-v1.webp",
        "meta_path": "editorial_inbox/auto_covers/" + article_id + f"-r{revision}-v1.json",
        "style_index": style_index,
        "headline": headline,
        "fact": brief["fact"],
        "hook": brief.get("hook", ""),
        "constraints": brief.get("constraints", ""),
        "article_title": draft["content"]["title"],
    }


def prompt_for(plan):
    style = STYLES[plan["style_index"]]
    where = {"left": "right 60%", "right": "left 60%", "bottom": "upper 70%"}[style["layout"]]
    return (
        "Produce a high-quality original landscape 16:9 editorial news illustration. "
        + style["art"] + " "
        "Essential true factual context (render a visual metaphor, not a fake screenshot): "
        + plan["fact"][:900] + ". "
        "Story hook: " + plan["hook"][:350] + ". "
        "Editorial constraints: " + plan["constraints"][:700] + ". "
        "Place the main visual action mostly in the " + where + " to leave room for real typography. "
        "Do not draw words, letters, logos, captions, headlines, website interfaces or watermarks. "
        "Avoid generic robots, holographic brains, neon server rooms, card-based UIs and streaming code. "
        "Strong singular concept, varied expressive composition. "
        "Any staged or satirical scene must look clearly illustrated, not like an authentic photograph."
    )


def wrap_lines(draw, words, font, max_width):
    lines, active = [], ""
    for word in words:
        candidate = (active + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] > max_width and active:
            lines.append(active)
            active = word
        else:
            active = candidate
    if active:
        lines.append(active)
    return lines


def render_webp(raw_bytes, plan):
    style = STYLES[plan["style_index"]]
    with Image.open(io.BytesIO(raw_bytes)) as image:
        image.load()
        if image.width < 500 or image.height < 280:
            raise ValueError("FLUX produced insufficient image dimensions")
        background = ImageOps.fit(image.convert("RGB"), (MIN_WIDTH, MIN_HEIGHT),
                                  method=Image.Resampling.LANCZOS).convert("RGBA")
    overlay = Image.new("RGBA", background.size)
    d = ImageDraw.Draw(overlay)
    layout = style["layout"]
    if layout == "left":
        panel, tx, top, max_width, max_lines = (0, 0, 690, MIN_HEIGHT), 66, 210, 560, 5
    elif layout == "right":
        panel, tx, top, max_width, max_lines = (920, 0, MIN_WIDTH, MIN_HEIGHT), 970, 210, 540, 5
    else:
        panel, tx, top, max_width, max_lines = (0, 635, MIN_WIDTH, MIN_HEIGHT), 85, 675, 1400, 2
    d.rectangle(panel, fill=style["background"])
    canvas = Image.alpha_composite(background, overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    if not FONT.exists():
        raise RuntimeError("Cyrillic font unavailable in image runner")
    brand = ImageFont.truetype(str(FONT), 24)
    if layout != "bottom":
        draw.text((tx, 93), "ХПИИ / НОВОСТИ", font=brand, fill=style["foreground"])
    else:
        draw.text((tx, 650), "ХПИИ", font=brand, fill=style["foreground"])
    title = " ".join(str(plan["headline"]).split())
    lines = None
    for size in range(82 if layout != "bottom" else 78, 31, -2):
        font = ImageFont.truetype(str(FONT), size)
        candidate = wrap_lines(draw, title.split(), font, max_width)
        line_h = int(size * 1.28)
        if (len(candidate) <= max_lines and
            all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in candidate)
            and top + len(candidate) * line_h < MIN_HEIGHT - 30):
            lines = candidate
            break
    if not lines:
        raise ValueError("Cannot fit accurate Cyrillic title without truncating it")
    for index, line in enumerate(lines):
        draw.text((tx, top + index * line_h), line, font=font, fill=style["foreground"])
    for quality in (83, 77, 71, 65, 58):
        buf = io.BytesIO()
        canvas.save(buf, format="WEBP", quality=quality, method=5)
        if len(buf.getvalue()) <= 750_000:
            return buf.getvalue()
    raise ValueError("Cover exceeds safe size; refusing to save oversized image")


def generate(root, plan, account_id, token):
    now = eligible(root)
    if now is None or any(now[k] != plan[k] for k in (
            "article_id", "revision", "updated_at", "draft_sha", "decision_sha",
            "image_path", "meta_path", "style_index", "headline")):
        raise ValueError("Approved text changed while artist was preparing; do not generate")
    if not account_id or not token:
        raise RuntimeError("Cloudflare Workers AI free-account credentials are not configured")
    raw = flux_cover_probe.generate(account_id, token, prompt_for(plan))
    result = render_webp(raw, plan)
    image_file = root / plan["image_path"]
    metadata_file = root / plan["meta_path"]
    if image_file.exists() or metadata_file.exists():
        raise RuntimeError("Cover already exists; refusing to overwrite")
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(result)
    info = {
        "schema_version": 1,
        "article_id": plan["article_id"],
        "text_revision": plan["revision"],
        "text_updated_at": plan["updated_at"],
        "source_draft_blob_sha": plan["draft_sha"],
        "source_decision_blob_sha": plan["decision_sha"],
        "status": "ready_for_cover_review",
        "image_path": plan["image_path"],
        "image_blob_sha": git_blob_sha(result),
        "width": MIN_WIDTH,
        "height": MIN_HEIGHT,
        "concept": (plan["fact"][:350] + " / " + STYLES[plan["style_index"]]["name"]),
        "headline": plan["headline"],
        "artist_notes": (
            "Создано автономным художником через бесплатный FLUX Workers AI; "
            "типографика наложена отдельно для грамотного кириллического текста. "
            "Требуется отдельное утверждение главреда. "
            "Изображение не является документальным кадром."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    metadata_file.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        # Validator is rooted to the editorial-intake worktree in the GitHub job.
        validate_cover(metadata_file)
    except Exception:
        # Keep failures out of the review queue.
        metadata_file.unlink(missing_ok=True)
        image_file.unlink(missing_ok=True)
        raise
    print("HPII_COVER_CANDIDATE_READY " + image_file.name + " " + str(len(result)) + " bytes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.generate:
        import os
        plan = safe_doc(args.plan_file)
        generate(root, plan, os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(),
                 os.getenv("CLOUDFLARE_API_TOKEN", "").strip())
    else:
        plan = eligible(root)
        if plan is None:
            args.plan_file.unlink(missing_ok=True)
            print("HPII_COVER_NO_ELIGIBLE_TEXT")
        else:
            args.plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
            print("HPII_COVER_PLANNED " + plan["article_id"] + " r" + str(plan["revision"]))


if __name__ == "__main__":
    main()
