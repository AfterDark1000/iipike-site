"""Topic tagging and reader navigation do not edit approved article text."""
import json
from pathlib import Path
import unittest

from scripts.site_topics import (
    TOPICS, validate_topics, infer_topics, render_topic_links, active_topics,
    render_topic_page, render_all_topics
)
from scripts.upgrade_article_navigation import clean_article_html
from scripts.publish_approved_article import render_article
from scripts.site_related import catalog_entries

ROOT = Path(__file__).resolve().parents[1]


class TopicNavigationTests(unittest.TestCase):
    def test_catalog_is_fixed_and_no_arbitrary_scanner_topic_can_be_used(self):
        self.assertEqual(len(TOPICS), 12)
        self.assertEqual(validate_topics(["agents", "engineering"]), ["agents", "engineering"])
        self.assertEqual(validate_topics([]), [])
        for bad in (["ai-infrastructure-super-duper"], ["../news"], ["agents", "agents"],
                    "agents", ["agents", "safety", "video"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_topics(bad)

    def test_representative_editorial_topics(self):
        examples = [
            ("GPT-6 Astra спроектировала гаджет, его изготовили на заводе",
             "ИИ-агенты помогли инженерам", {"engineering"}),
            ("Исследователи предупредили: ИИ-агентов невозможно выключить",
             "Угроза потери контроля", {"agents", "safety"}),
            ("Codex разогнал разработку, OpenAI перестроила Git!",
             "Новые репозитории для кодинга", {"development"}),
            ("OpenAI увеличила награды за взлом ChatGPT",
             "Баг-баунти и уязвимости", {"cybersecurity"}),
            ("ElevenLabs научила ИИ озвучивать сцены",
             "Речевые модели", {"audio"}),
            ("ИИ генерирует видео", "Новая видеомодель", {"video"}),
        ]
        for title, summary, expected in examples:
            with self.subTest(title=title):
                inferred = infer_topics(title, summary)
                self.assertTrue(set(inferred) & expected, inferred)
                self.assertLessEqual(len(inferred), 2)

    def test_linked_topics_do_not_replace_the_four_rubrics(self):
        rows = [
            {"id": "one", "url": "articles/one/", "title": "Первая новость",
             "summary": "А", "cover": "assets/a.webp", "rubric": "news",
             "published": "2026-11-04", "topics": ["agents", "safety"]},
            {"id": "two", "url": "articles/two/", "title": "Вторая новость",
             "summary": "Б", "cover": "assets/b.webp", "rubric": "skynet",
             "published": "2026-11-05", "topics": ["agents"]},
        ]
        page = render_topic_page("agents", rows)
        self.assertIn("articles/one/", page)
        self.assertIn("articles/two/", page)
        self.assertIn("Новости ИИ", page)
        self.assertIn("Скайнет просыпается", page)
        self.assertIn('rel="canonical" href="https://iipike.ru/topics/agents/"', page)
        self.assertIn('href="../../topics/agents/"', render_topic_links(["agents"]))
        self.assertIn("agents", active_topics(rows))
        outputs = render_all_topics(rows, ROOT)
        self.assertEqual(len(outputs), 1 + len(TOPICS))

    def test_approved_new_page_only_shows_clickable_rubric_and_topics(self):
        slug = "cnas-sovereign-agents-20261103"
        approved = json.loads((ROOT / "content" / "approved" / (slug + ".json")).read_text(encoding="utf-8"))
        records = [{"id": slug, "url": "articles/" + slug + "/",
                    "topics": ["agents", "safety"]}]
        page = render_article(approved, records, catalog_entries(ROOT))
        self.assertIn('<p class="kicker"><a href="../../rubrics/skynet/">Скайнет просыпается</a></p>', page)
        self.assertNotIn("Скайнет просыпается</a> / Скайнет", page)
        self.assertIn('<nav class="topic-links" aria-label="Темы статьи">', page)
        self.assertIn('href="../../topics/safety/"', page)
        self.assertIn('<p class="summary">' + approved["summary"] + '</p>', page)

    def test_archival_html_reformatting_preserves_article_text(self):
        slug = "nvidia-opublikovala-arkhitekturu-s-apparatnym-stop-kranom-dlya-69bf0"
        path = ROOT / "articles" / slug / "index.html"
        original = path.read_text(encoding="utf-8")
        edited = clean_article_html(original, ["agents", "safety"], slug)
        self.assertIn('<p class="kicker"><a href="../../rubrics/skynet/">Скайнет просыпается</a></p>', edited)
        self.assertNotIn("ИСТОРИЧЕСКИЙ АРХИВ</p>", edited)
        self.assertIn('href="../../topics/agents/"', edited)
        self.assertEqual(
            original.split('<article class="article-text">',1)[1],
            edited.split('<article class="article-text">',1)[1],
        )
        self.assertEqual(clean_article_html(edited, ["agents", "safety"], slug), edited)


if __name__ == "__main__":
    unittest.main()
