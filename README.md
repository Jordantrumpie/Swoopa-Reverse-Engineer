# Marketplace Car Flipper

A self-hosted alert tool for flipping cars on Facebook Marketplace, built to do what Swoopa does.
It watches your Marketplace searches sorted by **newest first**, saves every listing it sees
to a local database and **pushes an alert to your phone** when a new listing is worth it.

This is an original implementation. It does not use any Swoopa code or API.

## How it gets to listings first

- **Your searches only, polled often.** It runs every ~90s (jittered) on your own machine,
  without sharing a queue with other subscribers.
- **Newest-first sort is forced** on every search (`sortBy=creation_time_descend`).
- **Instant push** via ntfy, Telegram or Discord, with the photo and a link straight to the listing.
- **Your own comp database.** Every listing it sees is stored. Once you have enough similar cars
  (same make/model, ±2 years), it flags anything ≥20% under the median.
- **Price-drop alerts** on listings you've already seen.
- **Junk filter.** It drops salvage/rebuilt/parts/no-title/"down payment" dealer listings and $1
  placeholder prices, and scores up "must sell / OBO / moving" wording.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml   # edit searches, targets, notify
python -m flipper login              # opens a browser — log in to Facebook once
python -m flipper test-alert         # confirm your phone gets pinged
python -m flipper run                # watch forever (Ctrl+C to stop)
```

Other commands:
- `python -m flipper once` runs a single pass (good for cron).
- `python -m flipper comps` shows the median prices your DB has learned.
- `run --show` shows the browser window, which helps with debugging.

The first pass of each search only **seeds** the database. You won't get 40 alerts for
listings that were already there.

### Notifications
The easiest is [ntfy](https://ntfy.sh): install the app, subscribe to a long random topic name and
put that name in `notify.ntfy.topic`. Telegram and Discord are also supported (see the config).

## How it works

`flipper/fb.py` uses Playwright to load each search in a persistent Chromium profile that is
logged in as you. `flipper/extract.py` doesn't depend on Facebook's exact response layout. It walks
every JSON blob in the page and in the `/api/graphql/` responses and takes any object that has an
`id` and `marketplace_listing_title`, so small layout changes on Facebook's side don't break it.

```
flipper/
  fb.py       browser + Marketplace URL builder
  extract.py  listing extraction from HTML/GraphQL JSON
  parse.py    year/make/model, mileage, price parsing
  db.py       SQLite dedupe + comps
  scoring.py  alert rules (targets, comps, price drops, red flags)
  notify.py   ntfy / Telegram / Discord
```

Tests: `python -m unittest -v`

## Be realistic about the risks

Automated access breaks Facebook's Terms of Service, and Meta detects and restricts accounts
that scrape. To keep your account safe:
- Use moderate intervals (60–120s+) and only a few searches. Don't crank it to every 5 seconds.
- Use it for personal use only. Don't resell or republish the data.
- If you get checkpoints or a login wall, back off for a while.
- Think about using a secondary account, so a restriction doesn't hit your main profile.
