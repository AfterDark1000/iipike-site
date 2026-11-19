import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dzen_stage_a5_audit import METRIC_STATUS, audit_snapshot, catalog_rows, shortlist, topic_basis
from test_dzen_stage_a4_probe import card, snapshot


class DzenAudienceAuditTest(unittest.TestCase):
    def test_age_bands_have_disjoint_edges_and_count_missing_separately(self):
        items = [
            card(1, 24 * 60, views=0),
            card(2, 48 * 60 - 1, views=None, comments=None),
            card(3, 48 * 60, views=12, comments=1),
            card(4, 72 * 60, views=50, comments=0),
            card(5, 168 * 60, views=100000, comments=100),
        ]
        audit = audit_snapshot(*snapshot("channel", items))
        bins = audit["cohorts"]
        self.assertEqual([b["sample_size"] for b in bins], [2, 1, 1])
        self.assertEqual([b["median_views"] for b in bins], [0, 12, 50])
        self.assertEqual([b["comments_known"] for b in bins], [1, 1, 1])
        self.assertEqual([b["discussion_rate"] for b in bins], [0, 1, 0])
        self.assertEqual(audit["audience_status"], "insufficient_evidence")

    def test_high_frequency_first_page_does_not_prove_low_activity(self):
        items = [card(i, 25 * i, views=0) for i in range(1, 21)]
        audit = audit_snapshot(*snapshot("fast", items))
        self.assertEqual(audit["coverage"], "recent_page_only")
        self.assertEqual(audit["audience_status"], "insufficient_evidence")
        self.assertTrue(all(b["median_views"] is None and b["discussion_rate"] is None for b in audit["cohorts"]))
        self.assertTrue(audit["early_article_only_matches"])
        self.assertEqual(audit["early_article_only_matches"][0]["views"], 0)

    def test_topic_context_can_find_hidden_ai_subject_but_tags_alone_do_not(self):
        self.assertEqual(topic_basis("Обновление уже доступно", "Компания выпустила новую генеративную модель Claude."), "excerpt")
        self.assertEqual(topic_basis("Разговор с редактором", "Сегодня обсуждаем ИИ.", ["нейросети"]), "excerpt_and_tag")
        self.assertIsNone(topic_basis("Урологи сравнили две позы", "Участники вели дневник.", ["нейросети"]))

    def test_catalog_prioritizes_substantive_article_evidence_and_requires_metric_verification(self):
        rows = [
            {"slug": "broad", "title": "Обзор технологий", "publications30days": 25, "views30days": 5000},
            {"slug": "claimed", "title": "Нейросети каждый день", "publications30days": 1000, "views30days": 500000},
            {"slug": "other", "title": "Нейросети для авторов", "publications30days": 21, "views30days": 3200},
        ]
        items = [card(i, 24 * 60 + 75 * i, views=600, comments=1 if i < 3 else 0) for i in range(1, 7)]
        broad = audit_snapshot(*snapshot("broad", items))
        claimed = audit_snapshot(*snapshot("claimed", [card(i, 25 * i, title="Бытовые советы") for i in range(1, 8)]))
        data = {"initialData": {"items": rows}}
        raw = json.dumps([1, "2a:" + json.dumps(data, ensure_ascii=False)], ensure_ascii=False)
        public_rows = catalog_rows(f"<script>self.__next_f.push({raw})</script>")
        result = shortlist([("https://dzen.guru/channels", public_rows)], [broad, claimed])
        first, second = result["shortlist"]
        self.assertEqual(first["channel"], "broad")
        self.assertEqual(first["status"], "topic_and_discussion_observed")
        self.assertEqual(first["audience_status"], METRIC_STATUS)
        self.assertEqual(second["channel"], "other")
        self.assertEqual(second["status"], "needs_article_evidence")
