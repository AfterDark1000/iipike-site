"""Offline security/compatibility checks for editor-created HPII topic categories."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.site_topic_registry import (
    validate_manifest, load_extensions, require_append_only,
)
from scripts.site_topics import (
    TOPICS, BUILTIN_TOPICS, render_all_topics, render_topic_links, validate_topics,
)

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_ROWS = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
IDS = {r["id"] for r in BUILTIN_ROWS}

PROPOSAL = {
    "key": "virtual-worlds",
    "name": "Виртуальные 3D-миры",
    "description": "ИИ создаёт интерактивные трёхмерные миры и среды по описанию.",
    "why_not_existing": (
        "Это именно интерактивное создание мира и среды, а не "
        "генерация линейного видео или отдельных изображений."
    ),
    "evidence": [
        {"article_id": "google-search-ai-links"},
        {"source_url": "https://research.example.net/virtual-worlds"},
    ],
}


class EditorTopicRegistryTests(unittest.TestCase):
    def manifest(self, extra=None):
        return {"schema_version": 1, "topics": [copy.deepcopy(extra or PROPOSAL)]}

    def test_empty_registry_keeps_17_builtins_and_is_readable(self):
        self.assertEqual(len(BUILTIN_TOPICS), 17)
        self.assertGreaterEqual(len(TOPICS), 17)
        self.assertEqual(validate_manifest(
            {"schema_version": 1, "topics": []}, BUILTIN_TOPICS, IDS), {})
        self.assertEqual(require_append_only(
            {"schema_version": 1, "topics": []},
            {"schema_version": 1, "topics": []}), 0)

    def test_editor_can_add_new_topic_without_touching_python(self):
        m = self.manifest()
        added = validate_manifest(m, BUILTIN_TOPICS, IDS)
        self.assertEqual(added["virtual-worlds"][0], "Виртуальные 3D-миры")
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            (temp / "data").mkdir()
            (temp / "data" / "topic_extensions.json").write_text(
                json.dumps(m, ensure_ascii=False), encoding="utf-8")
            (temp / "news.json").write_text(
                json.dumps(BUILTIN_ROWS, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                load_extensions(temp / "data" / "topic_extensions.json",
                                BUILTIN_TOPICS, temp / "news.json"),
                added,
            )
        # Normal page-generation and validation use the same expanded
        # dictionary, including the automatic release's topic path allowlist.
        with patch.dict(TOPICS, added):
            self.assertEqual(validate_topics(["virtual-worlds"]),
                             ["virtual-worlds"])
            self.assertIn('href="../../topics/virtual-worlds/"',
                          render_topic_links(["virtual-worlds"]))
            outputs = render_all_topics(BUILTIN_ROWS, ROOT)
            self.assertIn(ROOT / "topics" / "virtual-worlds" / "index.html", outputs)
            body = outputs[ROOT / "topics" / "virtual-worlds" / "index.html"]
            self.assertIn('rel="canonical" href="https://iipike.ru/topics/virtual-worlds/"',
                          body)
            self.assertIn('name="robots" content="noindex, follow"', body)

    def test_unknown_arbitrary_scanner_labels_do_not_become_paths(self):
        with self.assertRaises(ValueError):
            validate_topics(["Генерация 3D-миров"])
        with self.assertRaises(ValueError):
            validate_topics(["virtual-worlds"])

    def test_reject_unsafe_or_duplicate_slugs(self):
        for slug in ("../steal", "new/section", "topics", "a" * 50,
                     "Virtual-Worlds", "a--b", "видео"):
            with self.subTest(slug=slug):
                item = copy.deepcopy(PROPOSAL)
                item["key"] = slug
                if slug == "topics":
                    item["key"] = "agents"
                with self.assertRaises(ValueError):
                    validate_manifest(self.manifest(item), BUILTIN_TOPICS, IDS)

    def test_reject_duplicate_and_nearly_identical_names(self):
        for name in ("ИИ агенты", "ИИ-агенты", "Виртуальные 3D-миры"):
            item = copy.deepcopy(PROPOSAL)
            item["name"] = name
            with self.subTest(name=name):
                if name == "Виртуальные 3D-миры":
                    m = {"schema_version": 1, "topics": [item, copy.deepcopy(item)]}
                else:
                    m = self.manifest(item)
                with self.assertRaises(ValueError):
                    validate_manifest(m, BUILTIN_TOPICS, IDS)

    def test_require_two_distinct_real_evidences(self):
        for evidence in (
            [],
            [{"article_id": "google-search-ai-links"}],
            [{"article_id": "google-search-ai-links"}] * 2,
            [{"article_id": "story-not-on-site"},
             {"source_url": "https://example.net/study"}],
            [{"source_url": "http://example.com"},
             {"source_url": "https://research.example.net/valid"}],
            [{"source_url": "https://user:password@example.net/a"},
             {"source_url": "https://research.example.net/valid"}],
            [{"source_url": "https://example.net:abc/a"},
             {"source_url": "https://research.example.net/valid"}],
            [{"source_url": "https://example.net/path", "article_id": "google-search-ai-links"},
             {"source_url": "https://research.example.net/valid"}],
        ):
            with self.subTest(evidence=evidence):
                item = copy.deepcopy(PROPOSAL)
                item["evidence"] = evidence
                with self.assertRaises(ValueError):
                    validate_manifest(self.manifest(item), BUILTIN_TOPICS, IDS)

    def test_reason_mandatory_for_editorial_semantic_review(self):
        item = copy.deepcopy(PROPOSAL)
        item["why_not_existing"] = "Оно лучше."
        with self.assertRaisesRegex(ValueError, "distinction"):
            validate_manifest(self.manifest(item), BUILTIN_TOPICS, IDS)

    def test_immutable_append_only_registry(self):
        old = self.manifest()
        newer = {"schema_version": 1, "topics": [
            copy.deepcopy(PROPOSAL),
            {**copy.deepcopy(PROPOSAL), "key": "second-theme",
             "name": "Другое направление"},
        ]}
        self.assertEqual(require_append_only(old, newer), 1)
        for changed in (
            {"schema_version": 1, "topics": []},
            {"schema_version": 1, "topics": [{**copy.deepcopy(PROPOSAL),
                                              "name": "Новая подпись"}]},
            {"schema_version": 1, "topics": list(reversed(newer["topics"]))},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                require_append_only(old, changed)


if __name__ == "__main__":
    unittest.main()
