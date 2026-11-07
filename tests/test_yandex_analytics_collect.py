"""Offline checks: no public leakage, wrong-site counter or fake success."""
import datetime as dt
import os
import unittest
from unittest.mock import patch

from scripts.yandex_analytics_collect import (
    AnalyticsError, GITHUB_API, PRIVATE_REPO, SITE,
    canonical_host, collect, date_window, ensure_private_repo,
    main, parse_metrika_report, pick_metrika_counter, request_json,
    save_private_json, choose_webmaster_host,
)


class YandexCollectorSafetyTests(unittest.TestCase):
    def test_dates_are_yekaterinburg_and_do_not_include_incomplete_today(self):
        # 18:15 UTC is 23:15 in Ust-Katav.
        thirty, seven, end = date_window(dt.datetime(2026, 11, 7, 18, 15, tzinfo=dt.timezone.utc))
        self.assertEqual((thirty, seven, end), ("2026-10-08", "2026-10-31", "2026-11-06"))

    def test_domain_matching_requires_exact_host(self):
        self.assertEqual(canonical_host("https://iipike.ru/articles/a"), SITE)
        self.assertEqual(canonical_host("iipike.ru"), SITE)
        self.assertNotEqual(canonical_host("not-iipike.ru"), SITE)
        self.assertNotEqual(canonical_host("iipike.ru.attacker.net"), SITE)

    def test_counter_never_pulls_other_yandex_properties(self):
        counters = {"counters": [
            {"id": 12, "status": "Active", "site2": {"site": "not-iipike.ru"}},
            {"id": 13, "status": "Active", "site2": {"site": "https://iipike.ru/"}}]}
        self.assertEqual(pick_metrika_counter(counters), "13")
        with self.assertRaisesRegex(AnalyticsError, "exactly one"):
            pick_metrika_counter(counters, "12")
        with self.assertRaisesRegex(AnalyticsError, "exactly one"):
            pick_metrika_counter({"counters": counters["counters"] * 2})

    def test_webmaster_requires_verified_host(self):
        data = {"hosts": [
            {"host_id": "http:wrong.ru:80", "ascii_host_url": "https://wrong.ru", "verified": True},
            {"host_id": "https:iipike.ru:443", "ascii_host_url": "https://iipike.ru/", "verified": True},
            {"host_id": "http:iipike.ru:80", "ascii_host_url": "http://iipike.ru/", "verified": False},
        ]}
        self.assertEqual(choose_webmaster_host(data), "https:iipike.ru:443")
        with self.assertRaisesRegex(AnalyticsError, "VERIFIED"):
            choose_webmaster_host({"hosts": data["hosts"][:1]})

    @patch("scripts.yandex_analytics_collect.request_json")
    def test_private_destination_is_mandatory(self, getter):
        for response in (
            {"full_name": PRIVATE_REPO, "private": False},
            {"full_name": "AfterDark1000/kot-bayun-wp", "private": True},
            {"full_name": PRIVATE_REPO, "private": True, "archived": True},
        ):
            getter.return_value = response
            with self.assertRaises(AnalyticsError):
                ensure_private_repo("opaque")
        getter.return_value = {"full_name": PRIVATE_REPO, "private": True}
        ensure_private_repo("opaque")
        self.assertEqual(getter.call_args.args[:2], (GITHUB_API, "/repos/" + PRIVATE_REPO))

    def test_unexpected_api_hosts_are_rejected_before_sending_token(self):
        with self.assertRaisesRegex(AnalyticsError, "Unexpected"):
            request_json("https://untrusted.example", "/steal", "very-secret-token")

    def test_report_does_not_invent_values_when_missing(self):
        with self.assertRaisesRegex(AnalyticsError, "missing totals"):
            parse_metrika_report({"data": []}, 10)

    @patch("scripts.yandex_analytics_collect.save_private_json")
    def test_output_path_restricted(self, unused):
        with self.assertRaisesRegex(AnalyticsError, "Unexpected statistics path"):
            save_private_json("opaque", "../../public-stats.json", {"visitors": 100})

    def test_missing_tokens_give_explicit_status_not_zero(self):
        with patch("scripts.yandex_analytics_collect.metrika_stats",
                   side_effect=AnalyticsError("HTTP 403")):
            report = collect(dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc),
                             "secret", "")
        self.assertEqual(report["metrika"]["status"], "error")
        self.assertEqual(report["webmaster"]["status"], "missing_credentials")
        self.assertNotIn("visits", report["webmaster"])

    @patch("scripts.yandex_analytics_collect.ensure_private_repo")
    @patch("scripts.yandex_analytics_collect.save_private_json")
    def test_missing_secrets_exit_without_request_or_storage(self, writer, checker):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main(), 0)
        checker.assert_not_called()
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
