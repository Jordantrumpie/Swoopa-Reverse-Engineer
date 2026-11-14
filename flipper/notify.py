"""Push alerts to your phone. Uses only the standard library."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


def format_alert(item: dict, verdict) -> tuple[str, str]:
    price = f"${item['price']:,.0f}" if item.get("price") else "?"
    title = f"{price} · {item.get('title', '')}"
    lines = []
    meta = " · ".join(x for x in [f"{item['mileage']:,} mi" if item.get("mileage") else "", item.get("location", "")] if x)
    if meta:
        lines.append(meta)
    lines += verdict.reasons
    if verdict.flags:
        lines.append("⚠ " + ", ".join(verdict.flags))
    lines.append(item["url"])
    return title, "\n".join(lines)


def _post(url: str, data: bytes, headers: dict) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


class Notifier:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def send(self, item: dict, verdict) -> None:
        title, body = format_alert(item, verdict)
        print(f"\n🚗 {title}\n{body}\n", flush=True)
        channels = [n for n in ("ntfy", "telegram", "discord") if self.cfg.get(n)]
        if not channels:
            log.warning("No phone notifications set up - add a notify: section to config.yaml")
        for name in channels:
            try:
                getattr(self, "_" + name)(self.cfg[name], title, body, item)
                log.info("%s: sent", name)
            except Exception as e:  # never let a notifier crash the watcher
                log.warning("%s notify failed: %s", name, e)

    def _ntfy(self, c, title, body, item):
        server = c.get("server", "https://ntfy.sh").rstrip("/")
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Click": item["url"],
                   "Priority": str(c.get("priority", 4)), "Tags": "car"}
        if item.get("photo"):
            headers["Attach"] = item["photo"]
        _post(f"{server}/{c['topic']}", body.encode(), headers)

    def _telegram(self, c, title, body, item):
        base = f"https://api.telegram.org/bot{c['bot_token']}"
        text = f"{title}\n{body}"
        if item.get("photo"):
            data = {"chat_id": c["chat_id"], "photo": item["photo"], "caption": text[:1024]}
            _post(base + "/sendPhoto", urllib.parse.urlencode(data).encode(),
                  {"Content-Type": "application/x-www-form-urlencoded"})
        else:
            data = {"chat_id": c["chat_id"], "text": text}
            _post(base + "/sendMessage", urllib.parse.urlencode(data).encode(),
                  {"Content-Type": "application/x-www-form-urlencoded"})

    def _discord(self, c, title, body, item):
        embed = {"title": title[:256], "url": item["url"], "description": body[:4000]}
        if item.get("photo"):
            embed["thumbnail"] = {"url": item["photo"]}
        _post(c["webhook_url"], json.dumps({"embeds": [embed]}).encode(), {"Content-Type": "application/json"})
