import datetime as dt
import unittest
from scripts import commenting_free_hunter as h

NOW = dt.datetime(2026,11,18,12,tzinfo=dt.timezone.utc)
DIRECT = "https://dzen.ru/a/Abcdef1234567890"

RSS = '''<?xml version="1.0"?><rss version="2.0"><channel><title>News</title>
<item><title>Нейросеть совершила открытие</title><link>https://dzen.ru/a/Abcdef1234567890?from=foo</link><pubDate>Wed, 18 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Нейросеть старый результат</title><link>https://dzen.ru/search?q=a</link></item>
<item><title>Нейросеть статья из издания</title><link>https://example.com/a/Abcdef1234567890</link></item>
<item><title>Нейросеть ещё один результат</title><link>https://www.google.com/url?url=https%3A%2F%2Fdzen.ru%2Fb%2FAbcdef1234567890</link></item>
</channel></rss>'''
ATOM = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>ChatGPT меняет наш мир</title><link rel="alternate" href="https://dzen.ru/a/Abcdef1234567890"/><published>2026-11-18T09:00:00Z</published></entry></feed>'''

class Tests(unittest.TestCase):
    def test_direct_article_only(self):
        self.assertEqual(h.safe_direct_link(DIRECT+"?foo=1"),DIRECT)
        for bad in ["http://dzen.ru/a/Abcdef1234567890", "https://dzen.ru/search?q=abc", "https://evil.dzen.ru/a/Abcdef1234567890", "https://dzen.ru/@channel", "https://dzen.ru/a/short", "https://dzen.ru.evil.com/a/Abcdef1234567890"]:
            self.assertIsNone(h.safe_direct_link(bad))
    def test_mixed_rss_only_direct_links(self):
        rows=h.parse_feed(RSS,"feed")
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]["dzen_url"],DIRECT)
        self.assertTrue(rows[1]["dzen_url"].startswith("https://dzen.ru/b/"))
    def test_atom_entries(self):
        rows=h.parse_feed(ATOM,"alerts")
        self.assertEqual(rows[0]["dzen_url"],DIRECT)
    def test_duplicates_keep_first_seen(self):
        config={"history_days":14,"max_items":100}
        first=h.build_queue(h.parse_feed(RSS,"feed"),{},NOW,config)
        again=h.build_queue(h.parse_feed(RSS,"feed"),first,NOW+dt.timedelta(hours=4),config)
        self.assertEqual(again["new_items"],0)
        self.assertEqual(len(again["items"]),2)
        self.assertEqual(first["items"][0]["first_seen_at"],again["items"][0]["first_seen_at"])
    def test_dates_are_not_falsely_dzen_dates(self):
        result=h.build_queue(h.parse_feed(RSS,"feed"),{},NOW,{"history_days":14})
        self.assertTrue(all(x["dzen_publication_date"] is None for x in result["items"]))
        self.assertTrue(all(x["url_status"]=="discovered_unopened" for x in result["items"]))
    def test_never_visit_dzen(self):
        urls=[]
        def fetcher(url):
            urls.append(url)
            return RSS
        conf={"queries":["ChatGPT"],"bing_news":True,"google_news":True,"bing_web":False,"history_days":14}
        result=h.run(conf,fetcher=fetcher,now=NOW)
        self.assertEqual(len(urls),2)
        self.assertTrue(all("dzen.ru" not in h.urllib.parse.urlsplit(url).hostname for url in urls))
        self.assertEqual(result["new_items"],1)
    def test_old_feed_results_are_discarded(self):
        old=RSS.replace("Wed, 18 Nov 2026 10:00:00 GMT", "Wed, 18 Nov 2020 10:00:00 GMT")
        result=h.run({"queries":["ИИ"],"bing_news":True,"google_news":False,"bing_web":False,"max_feed_age_hours":72,"history_days":14},fetcher=lambda _:old,now=NOW)
        self.assertEqual(result["new_items"],0)
        self.assertEqual(result["sources"][0]["outdated_or_undated"],2)

    def test_no_secret_leak_in_health(self):
        result=h.run({"queries":["ИИ"],"bing_news":False,"google_news":False,"bing_web":False}, secrets="https://www.google.com/alerts/feeds/123/456",fetcher=lambda _:ATOM,now=NOW)
        self.assertEqual(result["sources"][0]["source"],"Google Alerts RSS 1")
        self.assertNotIn("123/456",str(result))
    def test_web_rss_undated_link_kept_but_not_marked_fresh(self):
        rss='<?xml version="1.0"?><rss><channel><item><title>ChatGPT обновился</title><link>https://dzen.ru/a/Abcdef1234567890</link></item></channel></rss>'
        config={"queries":["ChatGPT"],"google_news":False,"bing_news":False,"bing_web":True,"history_days":14}
        result=h.run(config,fetcher=lambda _:rss,now=NOW)
        self.assertEqual(result["new_items"],1)
        self.assertEqual(result["items"][0]["feed_date_status"],"unknown")
        self.assertIsNone(result["items"][0]["dzen_publication_date"])

    def test_reject_unapproved_feed_source(self):
        for bad in ["https://evil.example/rss", "https://dzen.ru/search?q=a", "http://www.bing.com/news/search", "https://www.google.com/alerts/feeds/no/1"]:
            with self.assertRaises(ValueError):h.checked_feed(bad)

if __name__=="__main__": unittest.main()
