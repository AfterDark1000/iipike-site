"""Safe, dependency-free rendering of the ChatGPT editor's article formatting.

The editor sends structured blocks. Inline emphasis/links are a small, explicit
Markdown subset; raw HTML is ALWAYS escaped and javascript:/data:/file: links
are never clickable. No full Markdown or browser script execution.
"""
import html
import re
from urllib.parse import urlsplit

TEXT_TYPES = frozenset({"lead", "p", "h2", "h3", "quote"})
LIST_TYPES = frozenset({"ul", "ol"})
BLOCK_TYPES = TEXT_TYPES | LIST_TYPES | {"image"}
# Standalone Markdown illustrations are immutable, local, story-scoped assets.
# No remote URLs, traversal, SVG, HTML, data: URLs, or user-chosen paths.
IMAGE_SOURCE = re.compile(
    r"illustrations/(?P<story>[a-z0-9]+(?:-[a-z0-9]+)*)/"
    r"(?P<name>[a-z0-9][a-z0-9_-]{0,79}\\.(?:webp|png|jpg|jpeg))\\Z"
)
IMAGE_LINE = re.compile(r"!\\[(?P<alt>[^\\]\\n]{1,240})\\]\\((?P<src>[^()\\n]{1,240})\\)\\Z")


def image_asset(src):
    """Map a validated editorial illustration to one local, published asset."""
    if not isinstance(src, str) or not IMAGE_SOURCE.fullmatch(src):
        raise ValueError("Image must use illustrations/<story-id>/<name>.webp|png|jpg|jpeg")
    return "assets/editorial/inline/" + src[len("illustrations/"):]
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


def inline_html(text, site_links=None):
    """Escape ALL source HTML; selectively render a small Markdown subset."""
    if not isinstance(text, str):
        raise ValueError("Rich article fragment must be text")
    fragments = []
    pos = 0
    for match in _INLINE.finditer(text):
        fragments.append(html.escape(text[pos:match.start()], quote=True))
        if match.group("href") is not None:
            link = safe_href(match.group("href"))
            if site_links:
                # Only canonical Dzen article paths can be mapped. Tracking
                # parameters or fragments do not change article identity.
                parsed = urlsplit(link)
                if parsed.hostname == "dzen.ru":
                    canonical = "https://dzen.ru" + parsed.path.rstrip("/")
                    link = safe_href(site_links.get(canonical, link))
            # External sources stay in a new tab; site crosslinks navigate locally.
            attrs = (' target="_blank" rel="noopener noreferrer"'
                     if urlsplit(link).hostname != "iipike.ru" else "")
            fragments.append(
                '<a class="editorial-inline-link" href="' + html.escape(link, quote=True)
                + '"' + attrs + '>'
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
        elif kind == "image":
            if set(block) != {"type", "src", "alt"}:
                raise ValueError("Image block requires only src and alt")
            image_asset(block["src"])
            alt = _text(block["alt"], "image alt text", 240)
            if "\\n" in alt:
                raise ValueError("Image alt text must fit one line")
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


def render_blocks(blocks, site_links=None):
    """Render the exact approved block sequence into semantic safe HTML."""
    validate_blocks(blocks)
    rendered = []
    for block in blocks:
        kind = block["type"]
        if kind == "lead":
            rendered.append('<p class="lead">' + inline_html(block["text"], site_links) + "</p>")
        elif kind == "p":
            rendered.append("<p>" + inline_html(block["text"], site_links) + "</p>")
        elif kind in ("h2", "h3"):
            rendered.append(f"<{kind}>" + inline_html(block["text"], site_links) + f"</{kind}>")
        elif kind in LIST_TYPES:
            body = "".join("<li>" + inline_html(item, site_links) + "</li>" for item in block["items"])
            rendered.append(f'<{kind} class="editorial-list">' + body + f"</{kind}>")
        elif kind == "image":
            src = "../../" + image_asset(block["src"])
            rendered.append(
                '<figure class="editorial-inline-figure"><img loading="lazy" decoding="async" src="' +
                html.escape(src, quote=True) + '" alt="' +
                html.escape(block["alt"], quote=True) + '"></figure>'
            )
        else:
            quote_body = '<blockquote class="editorial-quote"><p>' + inline_html(block["text"], site_links) + "</p>"
            if block.get("attribution"):
                quote_body += "<footer><cite>" + inline_html(block["attribution"], site_links) + "</cite></footer>"
            rendered.append(quote_body + "</blockquote>")
    return "\n".join(rendered)


def markdown_to_blocks(source):
    """Parse the VERBATIM human-approved Dzen body, without a second rewrite.

    One Markdown source is authoritative. It is saved intact in the inbox and
    approved source; HTML is derived from it, preserving its paragraph/headings/
    lists/quote structure. Unsupported block syntax fails closed rather than
    silently disappearing. The standalone title lives in the JSON title fields.
    """
    if not isinstance(source, str) or not 400 <= len(source) <= 110_000:
        raise ValueError("article_markdown must be complete approved article text")
    if "\r" in source or "\x00" in source:
        raise ValueError("article_markdown has invalid newline/control encoding")
    blocks = []
    paragraph = []
    items = []
    list_kind = None
    quotation = []
    heading = re.compile(r"^(#{1,6})[ \t]+(.+)$")
    unordered = re.compile(r"^[-*][ \t]+(.+)$")
    numbered = re.compile(r"^[0-9]{1,2}[.)][ \t]+(.+)$")

    def flush_paragraph():
        if paragraph:
            blocks.append({"type": "p", "text": " ".join(paragraph)})
            paragraph.clear()

    def flush_list():
        nonlocal list_kind
        if items:
            blocks.append({"type": list_kind, "items": list(items)})
            items.clear()
        list_kind = None

    def flush_quote():
        if quotation:
            lines = list(quotation)
            quotation.clear()
            block = {"type": "quote"}
            if len(lines) > 1 and lines[-1].startswith("— "):
                block["attribution"] = lines.pop()[2:].strip()
            block["text"] = " ".join(lines)
            blocks.append(block)

    def flush_all():
        flush_paragraph()
        flush_list()
        flush_quote()

    for number, line in enumerate(source.split("\n"), 1):
        clean = line.strip()
        if not clean:
            flush_all()
            continue
        if clean.startswith(chr(96) * 3) or clean.startswith("~~~") or clean == "---":
            raise ValueError(f"Unsupported Markdown block at line {number}")
        heading_match = heading.fullmatch(clean)
        if heading_match:
            flush_all()
            hashes, body = heading_match.groups()
            if len(hashes) not in (2, 3):
                raise ValueError("Article title is separate; use ## and ### headings in body")
            blocks.append({"type": "h2" if len(hashes) == 2 else "h3", "text": body})
            continue
        if clean.startswith("!["):
            match = IMAGE_LINE.fullmatch(clean)
            if not match:
                raise ValueError(f"Malformed or unsupported image at line {number}")
            flush_all()
            image_asset(match.group("src"))
            blocks.append({"type": "image", "src": match.group("src"),
                           "alt": match.group("alt")})
            continue
        ul = unordered.fullmatch(clean)
        ol = numbered.fullmatch(clean)
        if ul or ol:
            kind = "ul" if ul else "ol"
            flush_paragraph()
            flush_quote()
            if list_kind not in (None, kind):
                flush_list()
            list_kind = kind
            items.append((ul or ol).group(1))
            continue
        if clean.startswith(">"):
            if not clean.startswith("> "):
                raise ValueError(f"Quote needs '> ' prefix on line {number}")
            flush_paragraph()
            flush_list()
            quote_line = clean[2:].strip()
            if not quote_line:
                raise ValueError("Empty quotation line")
            quotation.append(quote_line)
            continue
        # A new ordinary paragraph must terminate an adjacent quote/list.
        flush_list()
        flush_quote()
        paragraph.append(clean)
    flush_all()
    if blocks and blocks[0]["type"] == "p":
        blocks[0]["type"] = "lead"
    return validate_blocks(blocks, max_blocks=80, min_chars=400)
