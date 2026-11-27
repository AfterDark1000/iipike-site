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

from scripts.site_rich_text import markdown_to_blocks, validate_blocks, IMAGE_SOURCE, image_asset

STORY = re.compile(r"^editorial_inbox/stories/([a-z0-9]+(?:-[a-z0-9]+)*)\.json$")
COVER = re.compile(r"^editorial_inbox/covers/([a-z0-9]+(?:-[a-z0-9]+)*)\.(webp|png|jpg|jpeg)$")
ILLUSTRATION = re.compile(r"^editorial_inbox/illustrations/([a-z0-9]+(?:-[a-z0-9]+)*)/[a-z0-9][a-z0-9_-]{0,79}\.(?:webp|png|jpg|jpeg)$")
STABLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
IMAGE_EXTS = ("webp", "png", "jpg", "jpeg")
GH_REPO = "AfterDark1000/iipike-site"
MAX_AUTO_REBUILDS = 3  # No delays; each attempt uses fresh main and full tests.
# Verified issue #165: generated branch survived a safe main-drift refusal.
# Only this exact immutable bot commit may be automatically re-staged.
# Arbitrary preexisting review branches MUST NOT bypass manual review.
LEGACY_RECOVERY_RELEASES = {
    "un-autonomous-weapons-us-russia-20261117":
        "535d6f665af6f82d95670f16aa75ca87ea8df049",
}
# A changed publication index or publisher implementation requires a NEW
# scheduler cycle, not a retry with stale selection or loaded Python code.
# One chief-editor-approved reissue: old HTML/cover were left behind by
# the retraction even though the public news index and approved source
# were removed. This recovery never changes a published news.json row,
# never changes the old VK JPEG and requires exact historic Git blobs.
MANUAL_REISSUE_ID = "ii-kompanii-nanimayut-byvshikh-razvedchikov-za-za-8e599f8fd3fc906d"
MANUAL_REISSUE_PAGE_BLOB = "c37618328cd92397888d60599a5159f54d92c085"
MANUAL_REISSUE_COVER_BLOB = "fefc33582dd2b534fdf395faf9a67c709e22868d"
MANUAL_REISSUE_RECEIPT = "data/site_retractions/receipts/retract-20261122-counterintelligence.json"


RETRY_BLOCKING_PATHS = (
    "news.json", "data/entity_registry.json",
    "scripts/site_first_release_pr.py", "scripts/site_publication_queue.py",
    "scripts/site_first_inbox.py", "scripts/publish_approved_article.py",
    "scripts/site_entities.py", "scripts/site_release_quarantine.py",
    "scripts/site_rich_text.py",
    ".github/workflows/site-first-scheduled-release.yml",
)


class ArticleStageRejected(ValueError):
    """Candidate-specific staging failure before any release commit or push."""


class MainMovedDuringRelease(ValueError):
    """Main changed in a way safe to re-stage and validate from scratch."""


def classify_main_drift(base_sha, remote_sha):
    """Only unrelated fast-forward updates may trigger a transparent rebuild.

    Never retry over a rewritten main, a new site publication, or altered
    publisher/validator code. Retrying a site publication would bypass the
    queue's one-hour spacing, even if the Git merge itself were technically safe.
    """
    git("merge-base", "--is-ancestor", base_sha, remote_sha)
    sensitive = git("diff", "--name-only", f"{base_sha}..{remote_sha}",
                    "--", *RETRY_BLOCKING_PATHS).stdout.splitlines()
    if sensitive:
        raise ValueError("Main moved during editorial release; publishing-sensitive "
                         "changes require next scheduler cycle: " + ", ".join(sensitive))
    raise MainMovedDuringRelease(
        "Main moved during editorial release; safe to rebuild from new main")




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
            match = STORY.fullmatch(path) or COVER.fullmatch(path) or ILLUSTRATION.fullmatch(path)
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



def verified_manual_reissue(story_id, source_ref, base_ref):
    """Permit only the verified withdrawn #58 to reuse its exact page and cover."""
    if story_id != MANUAL_REISSUE_ID:
        return None
    slug = MANUAL_REISSUE_ID
    page = f"articles/{slug}/index.html"
    old_cover = f"assets/editorial/{slug}.webp"
    new_cover = f"editorial_inbox/covers/{slug}.webp"
    new_story = f"editorial_inbox/stories/{slug}.json"
    try:
        rows = json.loads(safe_git_blob_at(base_ref, "news.json"))
        receipt = json.loads(safe_git_blob_at(base_ref, MANUAL_REISSUE_RECEIPT))
        story = json.loads(safe_git_blob_at(source_ref, new_story))
        if (any(row.get("id") == slug for row in rows)
                or receipt.get("article_id") != slug
                or receipt.get("status") != "retracted_and_queued_for_manual_editor"
                or story.get("id") != slug
                or story.get("status") != "editor_approved"
                or story.get("approved_by") != "human_editor"):
            return None
        old_page_sha = git("rev-parse", f"{base_ref}:{page}").stdout.strip()
        old_cover_sha = git("rev-parse", f"{base_ref}:{old_cover}").stdout.strip()
        incoming_sha = git("rev-parse", f"{source_ref}:{new_cover}").stdout.strip()
        if (old_page_sha, old_cover_sha, incoming_sha) != (
                MANUAL_REISSUE_PAGE_BLOB,
                MANUAL_REISSUE_COVER_BLOB,
                MANUAL_REISSUE_COVER_BLOB):
            return None
        return page, old_cover
    except (ValueError, KeyError, subprocess.CalledProcessError):
        return None


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
    data = json.loads(safe_git_blob_at(ref, story))
    blocks = (markdown_to_blocks(data["article_markdown"])
              if "article_markdown" in data else validate_blocks(data.get("paragraphs")))
    illustrations = []
    for block in blocks:
        if block["type"] != "image":
            continue
        src = block["src"]
        match = IMAGE_SOURCE.fullmatch(src)
        if match is None or match.group("story") != story_id:
            raise ValueError("Image ID must match its approved story")
        path = "editorial_inbox/" + src
        if not exists_at(ref, path):
            print(f"AWAITING_ILLUSTRATIONS: {story_id} ({path})", flush=True)
            return None
        if path not in illustrations:
            illustrations.append(path)
    return (story, art[0], *illustrations)


def proposed_changes():
    output = git("status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    allowed = ("editorial_inbox/stories/", "editorial_inbox/covers/",
               "editorial_inbox/illustrations/",
               "assets/editorial/", "assets/vk/", "content/approved/", "articles/",
               "rubrics/", "topics/", "entities/")
    exact = {"news.json", "feed.xml", "dzen-rss.xml", "vk-rss.xml", "sitemap.xml", "index.html",
             "data/entity_registry.json"}
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
    # Inline illustrations are derived ONLY from the approved article's
    # verified, story-scoped image references in pending_paths(). Both their
    # editorial input and exact byte-for-byte copied public asset are required.
    inline_pairs = []
    for path in source_paths[2:]:
        match = ILLUSTRATION.fullmatch(path)
        if match is None or match[1] != story_id:
            raise ValueError("Refusing unapproved illustration path: " + path)
        public_path = image_asset(path.removeprefix("editorial_inbox/"))
        expected_files.update((path, public_path))
        inline_pairs.append((path, public_path))
    # Only compiler-defined rubrics can be changed during auto-release.
    # A newly populated "made-with-ai" archive is a legitimate fifth page.
    # Never derive this allowlist from untrusted story metadata.
    from scripts.site_rubrics import RUBRICS
    rubric_files = {"rubrics/" + name + "/index.html" for name in RUBRICS}
    # Exactly the canonical topic pages may be generated by the publisher.
    # The classifier must not expand paths from untrusted editor text.
    from scripts.site_topics import TOPICS
    topic_files = {"topics/index.html"} | {
        "topics/" + key + "/index.html" for key in TOPICS
    }
    # Only an explicit, published selection may change the controlled entity
    # registry. Its destination pages are derived from the existing allowlist,
    # not from any arbitrary editorial-provided path.
    from scripts.site_entities import load_registry, validate_editor_entities
    approved_path = Path("content/approved") / (story_id + ".json")
    if approved_path.is_file():
        approved = json.loads(approved_path.read_text(encoding="utf-8"))
        selected_companies, selected_products = validate_editor_entities(
            load_registry(), approved.get("companies"), approved.get("products"), compiled=True)
        if selected_companies or selected_products:
            expected_files.update(("data/entity_registry.json", "entities/index.html"))
            expected_files.update(
                "entities/" + kind + "/" + key + "/index.html"
                for kind, keys in (("companies", selected_companies),
                                   ("products", selected_products))
                for key in keys
            )
    changed = set(git("diff", "--name-only", f"{base_sha}..HEAD").stdout.splitlines())
    original_cover = f"assets/editorial/{story_id}.webp"
    if original_cover not in changed and verified_manual_reissue(story_id, "HEAD", base_sha):
        # The original WebP bytes are deliberately reused, so Git sees
        # no diff for the public cover. Verify the exact byte identity.
        if git("rev-parse", f"HEAD:{original_cover}").stdout.strip() != MANUAL_REISSUE_COVER_BLOB:
            raise ValueError("Manual reissue changed the approved historical cover")
        expected_files.discard(original_cover)
    if not expected_files <= changed:
        raise ValueError("Release is missing required site/article artifacts: "
                         + str(sorted(expected_files - changed)))
    for source, published in inline_pairs:
        source_blob = git("rev-parse", "HEAD:" + source).stdout.strip()
        published_blob = git("rev-parse", "HEAD:" + published).stdout.strip()
        if not source_blob or source_blob != published_blob:
            raise ValueError("Illustration public copy differs from approved source: " + published)
    # A new story may refresh inline crosslinks on *existing* approved
    # article pages. Allow these regenerated HTML files only when both the
    # page and its approved editorial source already existed in base main.
    # Do not relax the protection for assets, scripts, unapproved pages, etc.
    # RSS may be byte-identical for old paragraph-only site-first pilots.
    # Allow regeneration but never require an unrelated site release to
    # change an otherwise valid Dzen export.
    optional_files = {"dzen-rss.xml", "vk-rss.xml", f"assets/vk/{story_id}.jpg"}
    unexpected = changed - expected_files - optional_files - rubric_files - topic_files
    # Continuations must be exact generator outputs for compiler-approved listings.
    from scripts.site_rubrics import _LISTING_FILENAME
    continuation = {path for path in unexpected
                    if _LISTING_FILENAME.fullmatch(Path(path).name)}
    if continuation:
        from scripts.publish_approved_article import render_catalog_pages
        from scripts.site_rubrics import render_all
        from scripts.site_topics import render_all_topics
        from scripts.site_entities import render_all_entities
        root = Path(".")
        records = json.loads((root / "news.json").read_text(encoding="utf-8"))
        allowed_parents = {Path(p).parent for p in expected_files | rubric_files | topic_files
                           if p == "articles/index.html" or p.startswith(("rubrics/", "topics/", "entities/"))}
        generated = {**render_catalog_pages(records, root), **render_all(records, root),
                     **render_all_topics(records, root), **render_all_entities(records, root)}
        for path in continuation:
            target = root / path
            if (target.parent not in allowed_parents or target not in generated
                    or not target.is_file() or target.read_text(encoding="utf-8") != generated[target]):
                raise ValueError("Refusing invalid listing continuation: " + path)
        unexpected -= continuation
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
        classify_main_drift(base_sha, remote_head)
    # A normal non-forced push of a single reviewed commit. Fails closed if
    # branch protection or intervening updates disallow a fast-forward.
    try:
        git("push", "origin", "HEAD:refs/heads/main")
    except subprocess.CalledProcessError as error:
        # Catch a race between the fetch above and Git push. Auth/permission
        # failures are NEVER retried as concurrent writes.
        reason = (error.stderr or "").lower()
        if "fetch first" not in reason and "non-fast-forward" not in reason:
            raise
        git("fetch", "origin", "main")
        fresh = git("rev-parse", "origin/main").stdout.strip()
        if fresh != base_sha:
            classify_main_drift(base_sha, fresh)
        raise
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
    auto = os.environ.get("HPII_SITE_FIRST_AUTOPUBLISH") == "1"
    canonical_branch = "site-first/release/" + story_id
    existing = git("ls-remote", "--heads", "origin",
                   "refs/heads/" + canonical_branch).stdout.strip()
    if existing:
        # Do not treat an arbitrary old release PR as permission to publish.
        # Only the verified, immutable stalled auto-release #165 is recovered;
        # all other historical review branches retain the original manual gate.
        actual_sha = existing.split()[0]
        if not auto or LEGACY_RECOVERY_RELEASES.get(story_id) != actual_sha:
            print(f"EXISTING_RELEASE_REVIEW_REQUIRED: {story_id} {canonical_branch}", flush=True)
            return "exists"
        print(f"::warning::VERIFIED_STALE_AUTO_RELEASE_REBUILD: {story_id} "
              f"{canonical_branch}", flush=True)
    if auto:
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        if not (re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
                and re.fullmatch(r"[1-9][0-9]{0,5}", run_attempt)):
            raise ValueError("Automatic release retry requires valid GitHub run identity")
    attempts = MAX_AUTO_REBUILDS if auto else 1
    for attempt in range(1, attempts + 1):
        # Fetch a fresh, independently validated publication base EACH time.
        git("fetch", "origin", "main")
        reissue = verified_manual_reissue(story_id, ref, "origin/main")
        if exists_at("origin/main", f"articles/{story_id}/index.html") and not reissue:
            print(f"ALREADY_PUBLISHED: {story_id}", flush=True)
            return "published"
        base_sha = git("rev-parse", "origin/main").stdout.strip()
        # Auto attempts have per-run identities, so an interrupted attempt
        # cannot poison future scheduled runs. Manual PRs keep their stable
        # branch and explicit existing-branch review gate.
        branch = (f"site-first/auto/{story_id}/{run_id}-{run_attempt}-{attempt}"
                  if auto else canonical_branch)
        git("switch", "--detach", "origin/main")
        git("switch", "-c", branch)
        if reissue:
            # The old page and WebP are replaced only in this validated
            # release branch. No public-site downtime or lost VK JPEG.
            for obsolete in reissue:
                Path(obsolete).unlink()
        for path in paths:
            transfer_blob(ref, path)
        # Every retry regenerates from the exact approved editor sources.
        # Rebase/cherry-pick of old RSS or news.json is prohibited.
        try:
            run_checked(sys.executable, "scripts/site_first_inbox.py", story_id,
                        "--stage", "--publish")
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 3 or not auto:
                raise
            # The stage compiler rolls back its own output on rejection.
            # Remove only the editorial input files this attempt copied.
            for path in paths:
                if exists_at(base_sha, path):
                    raise RuntimeError("Cannot clean a pre-existing editorial input")
                Path(path).unlink(missing_ok=True)
            if reissue:
                git("restore", "--source=" + base_sha, "--worktree", "--", *reissue)
            git("switch", "--detach", base_sha)
            raise ArticleStageRejected("Final article staging validation rejected: " + story_id) from exc
        vk_result = subprocess.run([sys.executable, "scripts/build_vk_rss.py"], check=False)
        if vk_result.returncode != 0:
            print("::warning::VK_RSS_GENERATION_FAILED: site publication continues; "
                  "inspect VK RSS separately", flush=True)
        for cmd in (
            ("scripts/build_rubrics.py", "--check"),
            ("scripts/build_topics.py", "--check"),
            ("scripts/build_home_published.py", "--check"),
            ("scripts/build_sitemap.py", "--check"),
        ):
            run_checked(sys.executable, *cmd)
        run_checked(sys.executable, "-m", "unittest", "discover",
                    "-s", "tests", "-p", "test_*.py", "-q")
        files = proposed_changes()
        git("add", "--", *files)
        git("commit", "-m", f"site-first: prepare reviewed story and artwork {story_id}")
        # Preserve each validated attempt, without force pushing a preexisting
        # release branch or quietly deleting it.
        git("push", "origin", "HEAD:refs/heads/" + branch)
        if not auto:
            break
        try:
            auto_publish_site(story_id, base_sha, paths)
        except MainMovedDuringRelease as error:
            print("::warning::SITE_RELEASE_MAIN_DRIFT_REBUILD:", story_id,
                  f"attempt={attempt}/{attempts}", str(error), flush=True)
            if attempt < attempts:
                continue
            print("::warning::SITE_RELEASE_MAIN_DRIFT_DEFERRED:", story_id,
                  "no release confirmed; next story may proceed", flush=True)
            return "deferred_moving_main"
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
