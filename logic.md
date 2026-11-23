# Ranking logic

This file explains **why** the tool ranks posts the way it does. For how to run it, see [README.md](README.md).

The command-line tool (`blog_ranking.py`) and the web GUI (`docs/index.html`) use exactly the same rules below, and give the same results.

## 1. The problem

Team members publish posts on different dates in a quarter, and we want to reward the post that attracted the most readers. A raw visitor count isn't fair, for two reasons:

- **Time:** a post from early April has had three months to collect readers. A post from mid-June has had two weeks.
- **Shape of traffic:** blog traffic isn't spread evenly over time. A post usually gets a **launch spike** in its first 1–2 weeks (newsletter, social shares, the homepage), then a **long, slow tail** from search.

```
visitors/day
   │█
   │█
   │██
   │███
   │█████▄▄▄▂▂▂▂▂▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁
   └──────────────────────────────────── days since publish
     launch spike      long tail
```

Any fair method has to deal with both.

## 2. Which posts belong to a quarter

### Shifted publish window

A post published on June 28 would only have 2 days of data at quarter end. So each quarter's window is **shifted back by 15 days**:

| Quarter | Posts published | Visitor counts taken on |
|---|---|---|
| Q1 | Dec 16 – Mar 15 | Apr 14 |
| Q2 | Mar 16 – Jun 15 | Jul 15 |
| Q3 | Jun 16 – Sep 15 | Oct 15 |
| Q4 | Sep 16 – Dec 15 | Jan 14 |

- Every date falls in **exactly one** quarter, with no gaps and no double counting.
- A post from March 16 competes in Q2, not Q1. A post from June 20 competes in Q3.

### Snapshot 30 days after the window closes

Visitor counts are taken on **window end + 30 days** (Jul 15 for Q2). This guarantees:

- The newest eligible post (Jun 15) has been live for **31 days**, so its launch spike is complete.
- The oldest (Mar 16) has been live for 122 days. The longest post gets about 4× the time of the shortest, instead of 40× or more.
- Every post is measured on the **same day**, from the same report.

## 3. The formula

```
Days live   = Snapshot date − Publish date + 1        (both days counted)
Score       = Visitors ÷ √(Days live)
Percentage  = Score ÷ Σ(all eligible scores) × 100
Winner      = highest Percentage
```

### Why the square root?

Think of each post as having an underlying "pull" **q** (how interesting it is to readers). Its visitor count grows over time roughly as:

```
Visitors(t) ≈ q × t^α
```

To compare posts fairly we want to recover **q**, so we divide by t^α. The open question is what α (alpha, the exponent) should be:

| α | Divide by | Assumes traffic is… | Effect |
|---|---|---|---|
| 0 | nothing (raw total) | all on day one, nothing after | **Old posts win**: extra months count fully |
| 1 | days (per-day average) | flat, the same every day | **New posts win**: their launch spike isn't diluted yet |
| **0.5** | **√days** | **a spike, then a tail** | **Balanced** |

Real blog traffic sits between the two extremes, so α = 0.5 is a sensible, easy-to-explain middle ground. Each extra month still adds to a post's score, but less and less, which matches how readers actually arrive.

### Why a percentage?

The score itself has no natural unit ("visitors per root-day"). Turning it into a **share of the quarter's total** gives a number people understand ("Ravi's post earned 23% of the quarter"). All shares add up to 100%, and the ranking order doesn't change.

## 4. Same data, three methods

Q2 2026 sample (`examples/posts_sample.csv`), snapshot Jul 15:

| Post | Published | Visitors | Days | Raw share | Per-day share | **√ share** |
|---|---|---|---|---|---|---|
| InnoDB Buffer Pool | Mar 16 | 5,200 | 122 | **30.4%** 🥇 | 15.8% | 22.8% |
| PostgreSQL Vacuum | Apr 5 | 4,800 | 102 | 28.1% | 17.4% | **23.0%** 🥇 |
| MongoDB Indexes | May 20 | 3,100 | 57 | 18.1% | 20.1% | 19.9% |
| ProxySQL Rules | Jun 14 | 2,500 | 32 | 14.6% | **28.9%** 🥇 | 21.4% |
| Patroni Failover | Jun 15 | 1,500 | 31 | 8.8% | 17.9% | 13.0% |

- **Raw:** the oldest post wins, mostly on time.
- **Per-day:** a June post with half the readers wins, mostly on its launch spike.
- **Square root:** the April post wins. It had nearly as many readers as the March post in 20 fewer days. The June post comes a close third, which is about right.

Run `--method raw` or `--method perday` to see these yourself.

## 5. Tie-breaks and edge cases

| Situation | Rule |
|---|---|
| Equal score | Same rank (1, 1, 3…). Ordered by more visitors, then earlier publish date |
| Published before window | Excluded, counted in the earlier quarter |
| Published after window | Excluded, counted in the next quarter |
| Fewer than `--min-visitors` | Excluded, so a slow quarter doesn't produce a weak winner |
| Bad date or visitor value in the CSV | That row is skipped with a warning, and the rest is ranked |
| Counts pulled on a different day | Pass `--snapshot YYYY-MM-DD`. Days live are recalculated from that date |

## 6. Policies to agree on (outside the tool)

The tool ranks **posts**. Decide these up front and write them down:

- **Visitor metric:** use **unique visitors** (GA4 "Users"), not pageviews. Pageviews are easy to inflate by refreshing.
- **Traffic filters:** exclude internal/office IPs and known bots before exporting.
- **Co-authored posts:** share the award, or split credit evenly.
- **Several posts by one person:** rank the *best single post* (rewards quality) or add up an author's shares (rewards how much they write). The default here is best single post. For author totals, add up the `percentage` column from `--output` per author.
- **Paid or external promotion:** if one post got ads or a big outside push, either note it or exclude that traffic source.

## 7. Limitations and possible extensions

- **α = 0.5 is a reasoned default, not measured from your data.** With a few quarters of history, you could fit `log(visitors) = log(q) + α·log(days)` across past posts and use your own α.
- **Fixed-window alternative:** if your analytics can report visitors for any date range, you can measure every post over the *same* first N days (for example its first 30). That is fairer still, because it removes the time difference entirely. The trade-off is one date-range query per post instead of one export.
- **Topic size:** a MySQL post naturally has a bigger audience than a niche-tool post. If that matters, compare each post with its category's median score before ranking.
