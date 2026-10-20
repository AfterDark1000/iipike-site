"""HPI: curated primary-source news feeds and safe broad discovery.

First-party RSS/Atom announcements are evidence sources.
Hacker News/Algolia is ONLY a discovery index; retrieved links MUST resolve
to explicitly allowed first-party corporate domains and full official pages.
No paid APIs, scraping services, model calls, or social publishing.
"""
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

# Feed tuple: (publisher, official feed URL, accepted first-party article hosts).
# Some company feeds are experimental and may return 404/403; the scan logs that.
# Live success counts, not catalog count, are the measure of actual coverage.
SOURCES = (
    ("OpenAI", "https://openai.com/news/rss.xml", ("openai.com",)),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", ("deepmind.google",)),
    ("Google AI", "https://blog.google/innovation-and-ai/technology/ai/rss/",
     ("blog.google", "www.blog.google")),
    ("Mistral", "https://mistral.ai/news/rss", ("mistral.ai", "www.mistral.ai")),
    ("Google Research", "https://research.google/blog/rss/", ("research.google",)),
    ("Google Developers", "https://developers.googleblog.com/feeds/posts/default?alt=rss",
     ("developers.googleblog.com",)),
    ("Microsoft", "https://blogs.microsoft.com/feed/", ("blogs.microsoft.com",)),
    ("NVIDIA", "https://blogs.nvidia.com/feed/", ("blogs.nvidia.com",)),
    ("NVIDIA Developers", "https://developer.nvidia.com/blog/feed/", ("developer.nvidia.com",)),
    ("Amazon AWS AI", "https://aws.amazon.com/blogs/ai/feed/", ("aws.amazon.com",)),
    ("Amazon AWS ML", "https://aws.amazon.com/blogs/machine-learning/feed/", ("aws.amazon.com",)),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", ("huggingface.co",)),
    ("Cloudflare", "https://blog.cloudflare.com/rss/", ("blog.cloudflare.com",)),
    ("LangChain releases", "https://github.com/langchain-ai/langchain/releases.atom",
     ("github.com",)),
    ("Anthropic Claude Code releases", "https://github.com/anthropics/claude-code/releases.atom",
     ("github.com",)),
    ("Ollama releases", "https://github.com/ollama/ollama/releases.atom", ("github.com",)),
    ("ComfyUI releases", "https://github.com/comfyanonymous/ComfyUI/releases.atom", ("github.com",)),
    ("Transformers releases", "https://github.com/huggingface/transformers/releases.atom", ("github.com",)),
    ("vLLM releases", "https://github.com/vllm-project/vllm/releases.atom", ("github.com",)),
    ("OpenAI Codex releases", "https://github.com/openai/codex/releases.atom", ("github.com",)),
    ("Google Gemini CLI releases", "https://github.com/google-gemini/gemini-cli/releases.atom", ("github.com",)),
    ("llama.cpp releases", "https://github.com/ggml-org/llama.cpp/releases.atom", ("github.com",)),
)

# Fixed hostnames, not suffix matching. Do not allow user-submitted URLs, IPs,
# local services, credentials, lookalike domains, or uncontrolled redirects.
PRIMARY_HOSTS = {
    "openai.com", "help.openai.com", "platform.openai.com",
    "x.ai", "docs.x.ai",
    "anthropic.com", "www.anthropic.com", "docs.claude.com",
    "deepmind.google", "blog.google", "www.blog.google",
    "research.google", "developers.googleblog.com", "ai.google.dev",
    "mistral.ai", "www.mistral.ai", "docs.mistral.ai",
    "ai.meta.com", "about.fb.com", "engineering.fb.com",
    "blogs.microsoft.com", "www.microsoft.com",
    "blogs.nvidia.com", "developer.nvidia.com", "www.nvidia.com",
    "aws.amazon.com", "huggingface.co", "blog.cloudflare.com",
    "blog.langchain.dev", "www.perplexity.ai", "perplexity.ai",
    "deepseek.com", "www.deepseek.com",
    "alibabacloud.com", "www.alibabacloud.com", "qwenlm.github.io",
    "moonshot.ai", "www.moonshot.ai", "z.ai", "docs.z.ai",
    "www.apple.com", "machinelearning.apple.com",
    "www.adobe.com", "blog.adobe.com",
    "runwayml.com", "www.runwayml.com",
    "bfl.ai", "www.bfl.ai",
    "stability.ai", "www.stability.ai",
    "ideogram.ai", "about.ideogram.ai",
    "recraft.ai", "www.recraft.ai",
    "www.klingai.com", "klingai.com", "www.minimax.io", "minimax.io",
    "www.luma.ai", "lumalabs.ai", "www.pika.art", "pika.art",
    "elevenlabs.io", "www.elevenlabs.io",
    "suno.com", "www.suno.com", "udio.com", "www.udio.com",
    "canva.com", "www.canva.com", "www.freepik.com",
    "cursor.com", "www.cursor.com",
    "replit.com", "blog.replit.com",
    "lovable.dev", "www.lovable.dev",
    "yandex.ru", "yandex.com", "ya.ru", "sberbank.com",
    "github.com",
}
ALLOWED_HOSTS = PRIMARY_HOSTS | {
    host for _, feed_url, hosts in SOURCES for host in hosts
} | {urllib.parse.urlparse(url).hostname for _, url, _ in SOURCES}

# A GitHub "releases" page is first-party only when belonging to one of the
# tracked project maintainers. A random user repository is not an official source.
GITHUB_PROJECTS = {
    ("ollama", "ollama"), ("comfyanonymous", "comfyui"),
    ("huggingface", "transformers"), ("vllm-project", "vllm"),
    ("openai", "codex"), ("google-gemini", "gemini-cli"),
    ("ggml-org", "llama.cpp"), ("langchain-ai", "langchain"),
    ("anthropics", "claude-code"),
}

SEARCH_QUERIES = ("AI model", "Claude Gemini GPT", "AI video", "AI voice", "open source LLM")
RELEVANCE_TERMS = (
    "ai", "llm", "gpt", "gemini", "claude", "grok", "model", "neural",
    "agent", "inference", "video generation", "text to speech",
    "sora", "runway", "flux", "llama", "qwen", "deepseek", "anthropic",
    "mistral", "robotics", "multimodal", "machine learning",
    "copilot", "codex", "generative", "image generation", "diffusion",
    "уии", "нейросет", "искусственн",
)


def is_official_article(url):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in PRIMARY_HOSTS:
        return False
    try:
        if parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    if host == "github.com":
        parts = [x.casefold() for x in parsed.path.split("/") if x]
        return (len(parts) >= 4 and (parts[0], parts[1]) in GITHUB_PROJECTS
                and parts[2] == "releases" and parts[3] != "atom")
    if host == "huggingface.co":
        return parsed.path.startswith("/blog/")
    if host in ("www.apple.com", "yandex.ru", "ya.ru", "sberbank.com"):
        return len(parsed.path) > 8
    return len(parsed.path) > 2


def relevant_headline(title):
    s = (title or "").lower()
    # Short abbreviations require word boundaries ("ai" must not match "paid").
    return any(bool(re.search(r"\b" + re.escape(term) + r"\b", s))
               if len(term) <= 3 else term in s for term in RELEVANCE_TERMS)


def discover_hn(now, *, request_json=None, max_age_hours=72):
    """Fixed number of free HN searches; use only links to official sources."""
    if request_json is None:
        request_json = _hn_request
    cutoff = int((now - dt.timedelta(hours=max_age_hours)).timestamp())
    found = []
    urls = set()
    for query in SEARCH_QUERIES:
        params = urllib.parse.urlencode({
            "query": query, "tags": "story",
            "numericFilters": "created_at_i>" + str(cutoff),
            "hitsPerPage": "35",
        })
        try:
            data = request_json("https://hn.algolia.com/api/v1/search_by_date?" + params)
            rows = data.get("hits") or []
            for row in rows[:35]:
                url = row.get("url") or ""
                title = row.get("title") or ""
                if not is_official_article(url) or not relevant_headline(title):
                    continue
                published = dt.datetime.fromtimestamp(
                    int(row["created_at_i"]), tz=dt.timezone.utc)
                if not dt.timedelta(0) <= now - published <= dt.timedelta(hours=max_age_hours):
                    continue
                url = url.split("#", 1)[0]
                if url not in urls:
                    urls.add(url)
                    found.append({"url": url, "headline": title[:230],
                                  "discovered_at": published.isoformat()})
            print(f"HN discovery {query}: {len(rows)} indexed, "
                  f"{len(found)} distinct official-source links so far.", flush=True)
        except (ValueError, KeyError, TypeError, RuntimeError, urllib.error.URLError) as exc:
            print("HN discovery unavailable:", query, type(exc).__name__, flush=True)
    return found


def _hn_request(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "HPI-NewsDiscovery/1.0",
    })
    with urllib.request.urlopen(req, timeout=12) as response:
        if urllib.parse.urlparse(response.geturl()).hostname != "hn.algolia.com":
            raise RuntimeError("Unexpected HN API redirect")
        data = response.read(750_001)
        if len(data) > 750_000:
            raise RuntimeError("HN response too large")
        return json.loads(data)
