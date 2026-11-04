"""Safe, dependency-free rendering of the ChatGPT editor's article formatting.

The editor sends structured blocks. Inline emphasis/links are a small, explicit
Markdown subset; raw HTML is ALWAYS escaped and javascript:/data:/file: links
are never clickable. No full Markdown or browser script execution.
"""
import html
import re
from urllib.parse import urlsplit

TEXT_TYPES = frozenset({"lead", "p", "h2", "quote"})
LIST_TYPES = frozenset({"ul", "ol"})
BLOCK_TYPES = TEXT_TYPES | LIST_TYPES
# Only editor-used inline forms: **bold**, *italic*, [label](https://url).
# Keep the format deliberately small, auditable, and safe.
_INLINE = re.compile(
    r"\[(?P<label>[^\]\n]{1,200})\]\((?P<href>[^)\n]{1,2000})\)"
    r"|\*\*(?P<strong>[^*\n]{1,3000})\*\*"
    r"|\*(?P<em>[^*\n]{1,3000})\*"
)


def safe_href(value):
    """Check the actual URL; never trust a link destination in editorial text."""
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("Invalid inline link URL")
    if any(ord(c) < 33 or c == "\\" or c in '<>"' for c in value):
        raise ValueError("Unsafe character in inline link URL")
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and bool(url.hostname)
                 and not url.username and not url.password
                 and url.port in (None, 443))
    except ValueError as exc:
        raise ValueError("Invalid inline link URL") from exc
    if not valid:
        raise ValueError("Inline links must use safe HTTPS URLs")
    return value


def inline_html(text):
    """Escape ALL source HTML; selectively render a small Markdown subset."""
    if not isinstance(text, str):
        raise ValueError("Rich article fragment must be text")
    fragments = []
    pos = 0
    for match in _INLINE.finditer(text):
        fragments.append(html.escape(text[pos:match.start()], quote=True))
        if match.group("href") is not None:
            link = safe_href(match.group("href"))
            fragments.append(
                '<a class="editorial-inline-link" href="' + html.escape(link, quote=True)
                + '" target="_blank" rel="noopener noreferrer">'
                + html.escape(match.group("label"), quote=True) + '</a>'
            )
        elif match.group("strong") is not None:
            fragments.append("<strong>" + html.escape(match.group("strong"), quote=True) + "</strong>")
        else:
            fragments.append("<em>" + html.escape(match.group("em"), quote=True) + "</em>")
        pos = match.end()
    fragments.append(html.escape(text[pos:], quote=True))
    return "".join(fragments)


def _text(value, label, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Missing/invalid {label}")
    inline_html(value)  # Fail preflight for unsafe Markdown links.
    return value


def validate_blocks(blocks, *, max_blocks=None, min_chars=0):
    """Validate equally at ChatGPT inbox and approved-article publication."""
    if not isinstance(blocks, list) or len(blocks) < 2:
        raise ValueError("Article requires a lead and at least two blocks")
    if max_blocks is not None and len(blocks) > max_blocks:
        raise ValueError("Article has too many blocks")
    if not isinstance(blocks[0], dict) or blocks[0].get("type") != "lead":
        raise ValueError("First article paragraph must be a lead")
    total_chars = 0
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
            raise ValueError("Unsupported paragraph type")
        kind = block["type"]
        if idx and kind == "lead":
            raise ValueError("Article may only have one lead, as its first block")
        if kind in TEXT_TYPES:
            body = _text(block.get("text"), f"{kind} text", 3500 if kind == "quote" else 12000)
            total_chars += len(body)
            if kind == "quote" and "attribution" in block:
                _text(block["attribution"], "quote attribution", 240)
            elif kind != "quote" and "attribution" in block:
                raise ValueError("Attribution is supported only in quote blocks")
            if "items" in block:
                raise ValueError("Text blocks must not contain list items")
        else:
            if "text" in block or "attribution" in block:
                raise ValueError("List blocks require items, not text")
            items = block.get("items")
            if not isinstance(items, list) or not 1 <= len(items) <= 24:
                raise ValueError("List must contain 1–24 items")
            for item in items:
                total_chars += len(_text(item, "list item", 2000))
    if total_chars < min_chars:
        raise ValueError("Cannot publish incomplete article text")
    return blocks


def render_blocks(blocks):
    """Render the exact approved block sequence into semantic safe HTML."""
    validate_blocks(blocks)
    rendered = []
    for block in blocks:
        kind = block["type"]
        if kind == "lead":
            rendered.append('<p class="lead">' + inline_html(block["text"]) + "</p>")
        elif kind == "p":
            rendered.append("<p>" + inline_html(block["text"]) + "</p>")
        elif kind == "h2":
            rendered.append("<h2>" + inline_html(block["text"]) + "</h2>")
        elif kind in LIST_TYPES:
            body = "".join("<li>" + inline_html(item) + "</li>" for item in block["items"])
            rendered.append(f'<{kind} class="editorial-list">' + body + f"</{kind}>")
        else:
            quote_body = '<blockquote class="editorial-quote"><p>' + inline_html(block["text"]) + "</p>"
            if block.get("attribution"):
                quote_body += "<footer><cite>" + inline_html(block["attribution"]) + "</cite></footer>"
            rendered.append(quote_body + "</blockquote>")
    return "\n".join(rendered)
