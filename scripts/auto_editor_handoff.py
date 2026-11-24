#!/usr/bin/env python3
"""Hand off independently approved autonomous text + cover to the normal editorial inbox.

No direct publication. Only approved text and a separately approved exact image
may become editor_approved story and same-ID cover. Run via a guarded GitHub
Actions job with an immutable Git intake ref and the current main site archive.
"""
import argparse
import datetime as dt
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.site_first_inbox import ALLOWED_FIELDS, validate_story
from scripts.site_related import canonical_dzen_url, explicit_site_crosslinks, catalog_entries, validate_links

STORY_ID=re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DECISION_FILE=re.compile(
    r"editorial_inbox/auto_cover_decisions/(?P<id>[a-z0-9]+(?:-[a-z0-9]+)*)-r(?P<revision>[1-9][0-9]*)-v(?P<version>[1-9][0-9]*)\.json\Z"
)
INBOX="editorial_inbox"
TZ=ZoneInfo("Asia/Yekaterinburg")
MAX_STORY=128_000
MAX_IMAGE=800_000

# Exactly one already-approved legacy draft used noncanonical editorial topic
# labels. Translate ONLY this known immutable revision in the derived site
# payload; never edit the approved text or weaken site-level topic validation.
# The article's author-intended categories were security and AI industry.
REVIEWED_TOPIC_COMPAT = {
    ("ii-kompanii-nanimayut-byvshikh-razvedchikov-za-za-8e599f8fd3fc906d",
     "eda10f025a8cb76fdeab37651aa96400d35f3762",
     ("security", "ai-industry")): ("cybersecurity", "business"),
}


def derived_reviewed_topics(article_id, source_draft_sha, topics):
    if not isinstance(topics, list):
        return topics
    replacement = REVIEWED_TOPIC_COMPAT.get(
        (article_id, source_draft_sha, tuple(topics)))
    if replacement is None:
        return topics
    from scripts.site_topics import validate_topics
    remapped = validate_topics(list(replacement))
    print("REVIEWED_TOPIC_COMPAT_APPLIED:", article_id,
          ",".join(topics), "=>", ",".join(remapped), flush=True)
    return remapped

class HandoffBlocked(ValueError): pass

def git_bytes(*args):
    return subprocess.run(["git",*args],cwd=ROOT,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout

def read_git(ref,path):
    raw=git_bytes("show",f"{ref}:{path}")
    # Git blob hashes are content-addressed (including size and blob prefix).
    sha=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    actual=git_bytes("rev-parse",f"{ref}:{path}").decode().strip()
    if actual!=sha: raise HandoffBlocked("Git object changed while reading: "+path)
    return raw,sha

def json_object(ref,path):
    raw,sha=read_git(ref,path)
    if len(raw)>MAX_STORY: raise HandoffBlocked("JSON too large: "+path)
    doc=json.loads(raw.decode("utf-8"))
    if not isinstance(doc,dict): raise HandoffBlocked("JSON object required: "+path)
    return doc,sha

def exact(record,name,value):
    if record.get(name)!=value:
        raise HandoffBlocked("Approval consistency mismatch: "+name)

def approved_date(iso):
    stamp=dt.datetime.fromisoformat(iso.replace("Z","+00:00"))
    if stamp.tzinfo is None:raise HandoffBlocked("Human approval must have timezone")
    date=stamp.astimezone(TZ).date()
    if date>dt.datetime.now(TZ).date():
        raise HandoffBlocked("Future human approval date")
    return date.isoformat()

def verified_site_crosslinks(content, public):
    """Only map user-selected Dzen IDs with an exact matching published counterpart.
    Do not modify approved Markdown; the normal site renderer replaces href only.
    """
    given=content.get("site_crosslinks",{})
    if given is None:given={}
    if not isinstance(given,dict): raise HandoffBlocked("Bad site_crosslinks")
    mapped=dict(given)
    markdown=content.get("article_markdown","")
    for row in public:
        if not isinstance(row,dict):continue
        ident=row.get("dzen_id")
        if not ident or ident not in content.get("related_dzen_ids",[]) or ident in mapped:
            continue
        url=canonical_dzen_url(ident)
        if (row.get("url")=="articles/"+str(row.get("id"))+"/" and
                row.get("dzen_url")==url and "]("+url in markdown):
            mapped[ident]=row["id"]
    return mapped

def candidate_paths(id,revision,version):
    stem=f"{id}-r{revision}-v{version}"
    return {
      "draft":f"{INBOX}/auto_drafts/{id}.json",
      "text":f"{INBOX}/auto_decisions/{id}-r{revision}.json",
      "cover_meta":f"{INBOX}/auto_covers/{stem}.json",
      "cover_image":f"{INBOX}/auto_covers/{stem}.webp",
      "decision":f"{INBOX}/auto_cover_decisions/{stem}.json",
      "story":f"{INBOX}/stories/{id}.json",
      "image":f"{INBOX}/covers/{id}.webp",
      "marker":f"{INBOX}/auto_handoffs/{stem}.json",
    }

def build_candidate(ref, main_root, id, revision, version):
    if not STORY_ID.fullmatch(id) or len(id)>72:
        raise HandoffBlocked("Unsupported editorial story ID")
    paths=candidate_paths(id,revision,version)
    approval,approval_sha=json_object(ref,paths["decision"])
    exact(approval,"article_id",id)
    exact(approval,"text_revision",revision)
    exact(approval,"cover_version",version)
    exact(approval,"action","approve_cover")
    exact(approval,"status","cover_approved_handoff_pending")
    if approval.get("decided_by")!="AfterDark1000":raise HandoffBlocked("Cover decision is not owner's")
    draft,draft_sha=json_object(ref,paths["draft"])
    text,text_sha=json_object(ref,paths["text"])
    cover,cover_sha=json_object(ref,paths["cover_meta"])
    image,image_sha=read_git(ref,paths["cover_image"])
    exact(draft,"article_id",id)
    exact(draft,"revision",revision)
    exact(draft,"status","ready_for_review")
    exact(text,"article_id",id)
    exact(text,"revision",revision)
    exact(text,"updated_at",draft["updated_at"])
    exact(text,"action","approve_text")
    exact(text,"status","text_approved_cover_pending")
    exact(text,"draft_blob_sha",draft_sha)
    if text.get("decided_by")!="AfterDark1000":raise HandoffBlocked("Text decision is not owner's")
    exact(cover,"schema_version",1)
    exact(cover,"article_id",id)
    exact(cover,"text_revision",revision)
    exact(cover,"text_updated_at",draft["updated_at"])
    exact(cover,"source_draft_blob_sha",draft_sha)
    # A candidate created before text approval is bound to the exact draft,
    # not a nonexistent decision. Older candidates retain the stronger binding.
    if "source_decision_blob_sha" not in cover:
        raise HandoffBlocked("Cover metadata has no approval binding field")
    if cover["source_decision_blob_sha"] is not None:
        exact(cover,"source_decision_blob_sha",text_sha)
    exact(cover,"status","ready_for_cover_review")
    exact(cover,"image_path",paths["cover_image"])
    exact(cover,"image_blob_sha",image_sha)
    exact(approval,"text_updated_at",draft["updated_at"])
    exact(approval,"cover_blob_sha",image_sha)
    exact(approval,"cover_metadata_blob_sha",cover_sha)
    exact(approval,"source_draft_blob_sha",draft_sha)
    # Both independent human approvals are still mandatory. A cover approval
    # recorded first may have null for the then-nonexistent text decision.
    if "source_text_decision_blob_sha" not in approval:
        raise HandoffBlocked("Cover decision has no text binding field")
    if approval["source_text_decision_blob_sha"] is not None:
        exact(approval,"source_text_decision_blob_sha",text_sha)
    elif cover["source_decision_blob_sha"] is not None:
        raise HandoffBlocked("Legacy approved-text cover cannot lose its text approval binding")
    if not 1024<=len(image)<=MAX_IMAGE:raise HandoffBlocked("WebP exceeds size policy")
    if image[:4]!=b"RIFF" or image[8:12]!=b"WEBP":
        raise HandoffBlocked("Not actual WebP bytes")
    try:
        with Image.open(BytesIO(image)) as visual:
            width,height=visual.size
            if visual.format!="WEBP" or width<640 or height<360 or abs(width/height-16/9)>.02:
                raise HandoffBlocked("Unsafe image dimensions or format")
            visual.load()
    except (OSError,UnidentifiedImageError) as exc:
        raise HandoffBlocked("WebP image cannot be decoded") from exc
    exact(cover,"width",width);exact(cover,"height",height)
    content=draft.get("content")
    if not isinstance(content,dict):raise HandoffBlocked("Missing approved editor content")
    allowed_content=ALLOWED_FIELDS - {"id","schema_version","status","approved_by","approved_at"}
    # The pilot's threads/x text is separate metadata, never published by this handoff.
    story={k:content[k] for k in allowed_content if k in content}
    if "topics" in story:
        story["topics"] = derived_reviewed_topics(id, draft_sha, story["topics"])
    # The ordinary site/VK publisher expects a single-line optional summary.
    # Autonomous drafts may preserve paragraph breaks. Normalize whitespace
    # ONLY in the derived site payload, not in the owner's approved source.
    # Any non-whitespace content violation remains blocked by validate_story.
    for key in ("vk_title", "vk_summary"):
        if isinstance(story.get(key), str):
            story[key] = " ".join(story[key].split())
    story.update({
       "schema_version":1,"id":id,"status":"editor_approved",
       "approved_by":"human_editor","approved_at":approved_date(text["decided_at"])
    })
    public=json.loads((main_root/"news.json").read_text(encoding="utf-8"))
    if any(x.get("id")==id or
           (isinstance(x.get("title"),str) and x["title"].casefold()==str(story.get("title","")).casefold())
           for x in public):
        raise HandoffBlocked("Already published or duplicate headline")
    if (main_root/"articles"/id/"index.html").exists():
        raise HandoffBlocked("Published page already exists")
    story["site_crosslinks"]=verified_site_crosslinks(content,public)
    # The normal publisher also checks Dzen provenance, so validate it here,
    # not after admitting a potentially blocking item to the queue.
    links=explicit_site_crosslinks(story,public)
    validate_links(story.get("related_dzen_ids",[]),
                   catalog_entries(main_root),site_crosslinks=links)
    with tempfile.TemporaryDirectory(prefix="hpii-handoff-") as directory:
        root=Path(directory)
        for name in ("news.json",):
            (root/name).symlink_to((main_root/name).resolve())
        (root/"articles").symlink_to((main_root/"articles").resolve(),target_is_directory=True)
        story_dir=root/INBOX/"stories";story_dir.mkdir(parents=True)
        (story_dir/(id+".json")).write_text(json.dumps(story,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        # validate_story ensures the exact ordinary editorial handoff contract.
        validate_story(root,id)
    record={
       "schema_version":1,"article_id":id,"text_revision":revision,
       "cover_version":version,"status":"handed_off_to_site_queue",
       "source_draft_blob_sha":draft_sha,"text_decision_blob_sha":text_sha,
       "cover_metadata_blob_sha":cover_sha,"cover_blob_sha":image_sha,
       "cover_decision_blob_sha":approval_sha,
       "text_approved_at":text["decided_at"],"cover_approved_at":approval["decided_at"],
       "story_path":paths["story"],"cover_path":paths["image"],
       "site_queue":story.get("site_queue","standard"),
       "social_posts":"prepared_in_auto_draft_not_dispatched",
       "note":"Derived from separately human-approved text and image; no direct publication."
    }
    raw_story=(json.dumps(story,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    if len(raw_story)>MAX_STORY:raise HandoffBlocked("Handoff story too large")
    return paths,raw_story,image,(json.dumps(record,ensure_ascii=False,indent=2)+"\n").encode()

def scan(ref,main_root,output_dir):
    paths=git_bytes("ls-tree","-r","--name-only",ref,"--",f"{INBOX}/auto_cover_decisions").decode().splitlines()
    present=set(git_bytes("ls-tree","-r","--name-only",ref,"--",
       f"{INBOX}/stories",f"{INBOX}/covers",f"{INBOX}/auto_handoffs").decode().splitlines())
    options=[]
    for path in paths:
        match=DECISION_FILE.fullmatch(path)
        if match:
            id=match["id"];rev=int(match["revision"]);version=int(match["version"])
            names=candidate_paths(id,rev,version)
            if names["marker"] in present:continue
            if names["story"] in present or names["image"] in present:
                print("BLOCKED_EXISTING_EDITORIAL_INPUT:",id,flush=True)
                continue
            options.append((id,rev,version))
    # Preserve the news-pool FIFO when multiple reviewed candidates exist.
    # Read-only examination cannot change one approved item into another.
    examined=[]
    for id,rev,version in options:
        try:
            draft,_=json_object(ref,f"{INBOX}/auto_drafts/{id}.json")
            num=draft.get("pool_sequence")
            seq=num if type(num) is int and num>=0 else 999999999
            examined.append((seq,id,rev,version))
        except (ValueError,KeyError,json.JSONDecodeError,subprocess.CalledProcessError) as err:
            print("BLOCKED_AUTO_HANDOFF:",id,str(err)[:220],flush=True)
    examined.sort()
    output_dir.mkdir(parents=True,exist_ok=True)
    for _,id,rev,version in examined:
        try:
            names,story,image,record=build_candidate(ref,main_root,id,rev,version)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError,subprocess.CalledProcessError) as err:
            print("BLOCKED_AUTO_HANDOFF:",id,str(err)[:250],flush=True)
            continue
        content={
          names["story"]:story,names["image"]:image,names["marker"]:record
        }
        for path,data in content.items():
            dest=output_dir/path
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(data)
        manifest={"article_id":id,"files":list(content)}
        (output_dir/"handoff_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print("AUTO_HANDOFF_STAGED:",id,"bytes=",len(image),
              "queue=standard" if b'"site_queue": "priority"' not in story else "queue=priority",
              flush=True)
        return manifest
    manifest={"article_id":None,"files":[]}
    (output_dir/"handoff_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("NO_APPROVED_AUTO_HANDOFF: no eligible candidate",flush=True)
    return manifest

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-ref",default="origin/editorial-intake")
    p.add_argument("--site-root",type=Path,default=ROOT)
    p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args()
    if a.source_ref not in ("origin/editorial-intake",):
        p.error("Only the pinned editorial intake ref may be used")
    scan(a.source_ref,a.site_root.resolve(),a.output_dir.resolve())
