import csv
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import blog_ranking as br  # noqa: E402


class WindowTests(unittest.TestCase):
    def test_q2_window(self):
        self.assertEqual(br.eligibility_window(2, 2026), (date(2026, 3, 16), date(2026, 6, 15)))

    def test_q1_starts_previous_year(self):
        self.assertEqual(br.eligibility_window(1, 2026), (date(2025, 12, 16), date(2026, 3, 15)))

    def test_windows_have_no_gaps_or_overlaps(self):
        for q in (1, 2, 3):
            _, end = br.eligibility_window(q, 2026)
            start_next, _ = br.eligibility_window(q + 1, 2026)
            self.assertEqual((start_next - end).days, 1)
        _, q4_end = br.eligibility_window(4, 2026)
        q1_start, _ = br.eligibility_window(1, 2027)
        self.assertEqual((q1_start - q4_end).days, 1)

    def test_default_snapshot(self):
        self.assertEqual(br.default_snapshot(date(2026, 6, 15)), date(2026, 7, 15))


class ScoreTests(unittest.TestCase):
    def test_days_live_inclusive(self):
        self.assertEqual(br.days_live(date(2026, 7, 15), date(2026, 7, 15)), 1)
        self.assertEqual(br.days_live(date(2026, 3, 16), date(2026, 7, 15)), 122)

    def test_methods(self):
        self.assertAlmostEqual(br.score(400, 16, "sqrt"), 100.0)
        self.assertAlmostEqual(br.score(400, 16, "perday"), 25.0)
        self.assertAlmostEqual(br.score(400, 16, "raw"), 400.0)


class RankTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = br.eligibility_window(2, 2026)
        self.snap = br.default_snapshot(self.end)

    def post(self, title, d, v):
        return {"title": title, "author": title, "publish_date": d, "visitors": v, "url": ""}

    def test_sample_example(self):
        posts = [
            self.post("A", date(2026, 3, 16), 5200),
            self.post("B", date(2026, 4, 5), 4800),
            self.post("C", date(2026, 5, 20), 3100),
            self.post("D", date(2026, 6, 14), 2500),
            self.post("E", date(2026, 6, 15), 1500),
            self.post("F", date(2026, 6, 20), 2200),
            self.post("G", date(2026, 3, 10), 6000),
        ]
        ranked, excluded = br.rank_posts(posts, self.start, self.end, self.snap)
        self.assertEqual([p["title"] for p in ranked], ["B", "A", "D", "C", "E"])
        self.assertEqual({p["title"] for p in excluded}, {"F", "G"})
        self.assertAlmostEqual(sum(p["percentage"] for p in ranked), 100.0)
        self.assertAlmostEqual(ranked[0]["percentage"], 22.98, places=2)

    def test_ties_share_rank(self):
        posts = [self.post("X", date(2026, 4, 1), 1000), self.post("Y", date(2026, 4, 1), 1000)]
        ranked, _ = br.rank_posts(posts, self.start, self.end, self.snap)
        self.assertEqual([p["rank"] for p in ranked], [1, 1])

    def test_min_visitors(self):
        posts = [self.post("X", date(2026, 4, 1), 100), self.post("Y", date(2026, 4, 1), 1000)]
        ranked, excluded = br.rank_posts(posts, self.start, self.end, self.snap, min_visitors=300)
        self.assertEqual([p["title"] for p in ranked], ["Y"])
        self.assertEqual(excluded[0]["title"], "X")


class CsvTests(unittest.TestCase):
    def test_load_flexible_headers_and_formats(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Name", "Blog Title", "Date Posted", "Unique Visitors"])
            w.writerow(["Asha", "One", "05/04/2026", "4,800"])
            w.writerow(["Ravi", "Two", "not-a-date", "10"])
            w.writerow(["Meera", "Three", "2026-04-06", ""])
            path = fh.name
        try:
            posts, errors = br.load_posts(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["publish_date"], date(2026, 4, 5))
        self.assertEqual(posts[0]["visitors"], 4800)
        self.assertEqual(posts[0]["author"], "Asha")
        self.assertEqual(posts[0]["title"], "One")
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
