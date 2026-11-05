#!/usr/bin/env python3
"""Prepare a site-first RELEASE PULL REQUEST when approved story + cover arrive.

Run only in GitHub Actions on branch editorial-intake. The input branch is an
inbox; this script makes a fresh release branch based on origin/main, overlays
only the exact approved story + 16:9 artwork, runs the existing publisher and
all archive tests, then proposes a PR. It NEVER merges and NEVER posts to Dzen.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

STORY = re.compile(r"^editorial_inbox/stories/([a-z0-9]+(?:-[a-z0-9]+)*)\.json$")
COVER = re.compile(r"^editorial_inbox/covers/([a-z0-9]+(?:-[a-z0-9]+)*)\.(webp|png|jpg|jpeg)$")
STABLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
IMAGE_EXTS = ("webp", "png", "jpg", "jpeg")
GH_REPO = "AfterDark1000/iipike-site"


def changed_ids(event):
    """Get story IDs touched by the latest GitHub push or explicit retry.

    No traversal/commands or arbitrary file paths can become Git operations.
    """
    found = set()
    if event.get("inputs", {}).get("story_id"):
        story_id = event["inputs"]["story_id"]
        if not STABLE_ID.fullmatch(story_id) or len(story_id) > 72:
            raise ValueError("Invalid explicit story_id")
        return [story_id]
    for c in event.get("commits", []):
        for path in c.get("added", []) + c.get("modified", []):
            match = STORY.fullmatch(path) or COVER.fullmatch(path)
            if match and len(match[1]) <= 72:
                found.add(match[1])
    return sorted(found)


def git(*args, check=True, stdout=None):
    return subprocess.run(["git", *args], check=check,
                          stdout=stdout if stdout is not None else subprocess.PIPE,
                          stderr=subprocess.PIPE, text=stdout is None)


def candidate_ids_from_tree(ref):
    """GitHub Actions push event payloads sometimes omit commit file arrays.

    Read actual file paths from the immutable checked-out commit instead.
    The release script must never silently report success with zero candidates
    when the same commit already holds a story and its artwork.
    """
    output = git("ls-tree", "-r", "--name-only", ref, "--",
                 "editorial_inbox/stories", "editorial_inbox/covers").stdout
    found = set()
    for path in output.splitlines():
        match = STORY.fullmatch(path) or COVER.fullmatch(path)
        if match and len(match[1]) <= 72:
            found.add(match[1])
    return sorted(found)


def exists_at(ref, path):
    result = git("cat-file", "-e", f"{ref}:{path}", check=False)
    return result.returncode == 0


def safe_git_blob_at(ref, path):
    result = git("ls-tree", ref, "--", path).stdout.strip()
    if not result or not result.startswith("100644 blob "):
        raise ValueError(f"Not a regular Git file: {path}")
    return git("show", f"{ref}:{path}").stdout


def transfer_blob(ref, relative):
    """Write exact source blob bytes, including binary covers, without re-encoding."""
    dest = Path(relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise ValueError("Refusing to replace existing file: " + relative)
    mode = git("ls-tree", ref, "--", relative).stdout.strip().split()
    if len(mode) < 3 or mode[0] != "100644" or mode[1] != "blob":
        raise ValueError("Source file must be a plain Git blob: " + relative)
    with dest.open("wb") as out:
        git("show", f"{ref}:{relative}", stdout=out)


def pending_paths(ref, story_id):
    """Exactly one attached image; zero means safely wait."""
    story = f"editorial_inbox/stories/{story_id}.json"
    if not exists_at(ref, story):
        print(f"COVER_AWAITING_ARTICLE: {story_id}", flush=True)
        return None
    possible = [f"editorial_inbox/covers/{story_id}.{ext}" for ext in IMAGE_EXTS]
    art = [p for p in possible if exists_at(ref, p)]
    if not art:
        print(f"AWAITING_COVER: {story_id}", flush=True)
        return None
    if len(art) != 1:
        raise ValueError(f"Ambiguous images for {story_id}: {art}")
    return story, art[0]


def proposed_changes():
    output = git("status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    allowed = ("editorial_inbox/stories/", "editorial_inbox/covers/",
               "assets/editorial/", "content/approved/", "articles/",
               "rubrics/")
    exact = {"news.json", "feed.xml", "sitemap.xml", "index.html"}
    changed = []
    for row in output:
        name = row[3:]
        if " -> " in name:
            raise ValueError("Rename in release tree requires manual review")
        # Python tests intentionally compile .pyc inside untracked cache
        # directories. They are build byproducts, never release assets.
        # Continue blocking EVERY other unexpected path.
        if re.fullmatch(r"(?:[a-zA-Z0-9_-]+/)*__pycache__/[a-zA-Z0-9_.-]+\.pyc", name):
            continue
        if name not in exact and not name.startswith(allowed):
            raise ValueError("Unexpected modified file from publisher: " + name)
        changed.append(name)
    if not changed:
        raise ValueError("Publisher produced no release changes")
    return changed


def run_checked(*args):
    print("$ " + " ".join(args), flush=True)
    subprocess.run(args, check=True)


def auto_publish_site(story_id, base_sha, source_paths):
    """Fast-forward ONLY the already-tested site release, then request Pages build.

    GitHub Actions cannot open PRs with this repository's token, and pushes
    made via GITHUB_TOKEN do not trigger an ordinary Pages build on their own.
    The explicit REST rebuild request is therefore required. A failed request
    is reported as failure (the release branch remains for recovery).
    """
    expected_files = {
        source_paths[0], source_paths[1],
        "assets/editorial/" + Path(source_paths[1]).name,
        f"content/approved/{story_id}.json",
        f"articles/{story_id}/index.html",
        "news.json", "feed.xml", "sitemap.xml", "index.html",
        "articles/index.html",
    }
    rubric_files = {"rubrics/" + name + "/index.html" for name in (
        "news", "skynet", "what-are-you-doing", "quotes"
    )}
    changed = set(git("diff", "--name-only", f"{base_sha}..HEAD").stdout.splitlines())
    if not expected_files <= changed:
        raise ValueError("Release is missing required site/article artifacts: "
                         + str(sorted(expected_files - changed)))
    # A new story may refresh inline crosslinks on *existing* approved
    # article pages. Allow these regenerated HTML files only when both the
    # page and its approved editorial source already existed in base main.
    # Do not relax the protection for assets, scripts, unapproved pages, etc.
    unexpected = changed - expected_files - rubric_files
    for path in unexpected:
        match = re.fullmatch(r"articles/([a-z0-9]+(?:-[a-z0-9]+)*)/index\.html", path)
        if not match:
            raise ValueError("Refusing non-editorial changes in automatic release: " + path)
        old_slug = match[1]
        for old_path in (path, f"content/approved/{old_slug}.json"):
            tree = git("ls-tree", base_sha, "--", old_path).stdout.strip()
            if not tree.startswith("100644 blob ") or not tree.endswith("\t" + old_path):
                raise ValueError("Refusing non-editorial changes in automatic release: " + path)
    git("fetch", "origin", "main")
    remote_head = git("rev-parse", "origin/main").stdout.strip()
    if remote_head != base_sha:
        raise ValueError("Main moved during editorial release; refusing to overwrite it")
    # A normal non-forced push of a single reviewed commit. Fails closed if
    # branch protection or intervening updates disallow a fast-forward.
    git("push", "origin", "HEAD:refs/heads/main")
    print("AUTO_RELEASE_MAIN_UPDATED: " + story_id, flush=True)
    # Explicit Pages build is essential: GITHUB_TOKEN-originated pushes do not
    # trigger most additional workflows or the ordinary automatic Pages build.
    run_checked("gh", "api", "-X", "POST",
                f"repos/{GH_REPO}/pages/builds")
    print("PAGES_REBUILD_REQUESTED: " + story_id, flush=True)


def release_one(story_id, ref):
    paths = pending_paths(ref, story_id)
    if paths is None:
        return "waiting"
    branch = "site-first/release/" + story_id
    exists = git("ls-remote", "--heads", "origin", "refs/heads/" + branch).stdout
    if exists.strip():
        print(f"EXISTING_RELEASE_REVIEW_REQUIRED: {story_id} {branch}", flush=True)
        return "exists"
    # The live main branch is refreshed before every candidate. Never derive a
    # release branch from the potentially outdated editorial-intake site tree.
    git("fetch", "origin", "main")
    if exists_at("origin/main", f"articles/{story_id}/index.html"):
        print(f"ALREADY_PUBLISHED: {story_id}", flush=True)
        return "published"
    base_sha = git("rev-parse", "origin/main").stdout.strip()
    git("switch", "--detach", "origin/main")
    git("switch", "-c", branch)
    for path in paths:
        transfer_blob(ref, path)
    # This stage is the FIRST source of site publication timestamp; not the
    # approval day or the Dzen publication day.
    run_checked(sys.executable, "scripts/site_first_inbox.py", story_id, "--stage", "--publish")
    for cmd in (
        ("scripts/build_rubrics.py", "--check"),
        ("scripts/build_home_published.py", "--check"),
        ("scripts/build_sitemap.py", "--check")
    ):
        run_checked(sys.executable, *cmd)
    run_checked(sys.executable, "-m", "unittest", "discover",
                "-s", "tests", "-p", "test_*.py", "-q")
    files = proposed_changes()
    git("add", "--", *files)
    git("commit", "-m", f"site-first: prepare reviewed story and artwork {story_id}")
    git("push", "origin", "HEAD:refs/heads/" + branch)
    if os.environ.get("HPII_SITE_FIRST_AUTOPUBLISH") == "1":
        auto_publish_site(story_id, base_sha, paths)
        return "auto_published_rebuild_requested"
    source = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
    title = source["title"].replace("\n", " ").strip()[:92]
    pr_body = (
        "Первый выпуск на iipike.ru из рабочего ChatGPT-редактора.\\n\\n"
        f"Редакционный ID: {story_id}. Утверждённый заголовок: {title}.\\n\\n"
        "Статья и 16:9-обложка поступили независимо, сверены по одному ID. "
        "Полный текст и исходный URL проверены редактором; опубликованной "
        "статьи в Дзене ещё нет. Локальная сборка, все архивные регрессии, "
        "RSS, рубрики и Sitemap успешно проверены.\\n\\n"
        "**Выпуск:** PR необходимо проверить и объединить с main. Только после "
        "успешного GitHub Pages deploy вручную публиковать тот же заголовок в Дзене. "
        "Внешний кросспостинг и очереди Threads/X не изменяются."
    )
    # GitHub may prohibit GITHUB_TOKEN from creating PRs depending on repository
    # settings. A pushed release branch is retained, and we give a fallback URL.
    cmd = [
        "gh", "pr", "create", "--repo", GH_REPO, "--base", "main",
        "--head", branch, "--title", "ХПИИ: сайт первым — " + title,
        "--body", pr_body,
    ]
    try:
        subprocess.run(cmd, check=True, env=os.environ.copy())
        print(f"RELEASE_PR_CREATED: {branch}", flush=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"::warning::PR not created automatically ({type(exc).__name__}). "
              f"Ready branch: https://github.com/{GH_REPO}/compare/main...{branch}",
              flush=True)
    return "prepared"


def main():
    if os.environ.get("GITHUB_REPOSITORY") != GH_REPO:
        raise ValueError("Unexpected GitHub repository")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    source_sha = os.environ["GITHUB_SHA"]
    ids = changed_ids(event)
    # The GitHub Actions runner may receive a push event without 'commits',
    # even when a real new story/cover file triggered it. The git tree is
    # authoritative, unlike an optional/truncated webhook file list.
    tree_ids = candidate_ids_from_tree(source_sha)
    if not ids:
        ids = tree_ids
        if ids:
            print("PUSH_PAYLOAD_WITHOUT_FILES: recovered candidates from actual Git tree",
                  flush=True)
    if not ids:
        print("NO_EDITORIAL_CHANGES: no qualifying story/image IDs; nothing published")
        return
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    outcomes = {}
    for sid in ids:
        print(f"CHECKING_SITE_FIRST: {sid}", flush=True)
        outcomes[sid] = release_one(sid, source_sha)
    print("SUMMARY: " + json.dumps(outcomes, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
