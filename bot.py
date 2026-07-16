import json
import os
import re
import sys
import time
import traceback

import requests


def clean_slug(value):
    value = (value or "").strip().strip("@").strip()
    if "/" in value:
        value = value.rstrip("/").split("/")[-1]
    return value


DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN")
TWITTER_USERNAME = clean_slug(os.getenv("TWITTER_USERNAME")) or "heuresia"
LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT", "")
LINKEDIN_JSESSIONID = os.getenv("LINKEDIN_JSESSIONID", "")
LINKEDIN_COMPANY = clean_slug(os.getenv("LINKEDIN_COMPANY"))
LINKEDIN_PROFILE = clean_slug(os.getenv("LINKEDIN_PROFILE"))
BOT_NAME = os.getenv("BOT_NAME", "Heuresia Socials")
BOT_AVATAR_URL = os.getenv("BOT_AVATAR_URL", "")
STATE_FILE = "state.json"
MAX_POSTS_PER_RUN = 5


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    state = {}
    if os.path.exists("last_tweet.txt"):
        with open("last_tweet.txt") as f:
            legacy = f.read().strip()
        if legacy:
            state["x"] = legacy
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_to_discord(content):
    payload = {"username": BOT_NAME, "content": content}
    if BOT_AVATAR_URL:
        payload["avatar_url"] = BOT_AVATAR_URL
    response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=30)
    response.raise_for_status()


def patch_tweety_pinned_tweet():
    from tweety.types.usertweet import UserTweets

    original = UserTweets._get_pinned_tweet

    def safe_get_pinned_tweet(self, response):
        try:
            return original(self, response)
        except Exception:
            return None

    UserTweets._get_pinned_tweet = safe_get_pinned_tweet


def fetch_x_posts():
    from tweety import Twitter

    patch_tweety_pinned_tweet()
    print(f"[x] fetching @{TWITTER_USERNAME}")
    app = Twitter("session")
    app.load_auth_token(TWITTER_AUTH_TOKEN)
    tweets = list(app.get_tweets(TWITTER_USERNAME))
    items = []
    for tweet in tweets:
        items.append({
            "id": str(tweet.id),
            "url": f"https://fxtwitter.com/{TWITTER_USERNAME}/status/{tweet.id}",
        })
    return items


def linkedin_client():
    from linkedin_api import Linkedin
    from requests.cookies import cookiejar_from_dict

    jar = cookiejar_from_dict({
        "li_at": LINKEDIN_LI_AT,
        "JSESSIONID": LINKEDIN_JSESSIONID,
    })
    return Linkedin("", "", cookies=jar)


LINKEDIN_URN_PATTERN = re.compile(r"urn:li:(activity|ugcPost|share):(\d+)")


def find_post_urn(obj):
    match = LINKEDIN_URN_PATTERN.search(json.dumps(obj))
    if not match:
        return None, None
    return f"urn:li:{match.group(1)}:{match.group(2)}", match.group(2)


def find_texts(obj):
    texts = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "text" and isinstance(value, str):
                texts.append(value)
            else:
                texts.extend(find_texts(value))
    elif isinstance(obj, list):
        for value in obj:
            texts.extend(find_texts(value))
    return texts


def extract_linkedin_item(raw):
    urn, post_id = find_post_urn(raw)
    if not post_id:
        return None
    candidates = find_texts(raw)
    snippet = max(candidates, key=len) if candidates else ""
    return {
        "id": post_id,
        "text": snippet,
        "url": f"https://www.linkedin.com/feed/update/{urn}",
    }


def parse_linkedin(raw_list, label):
    items = [item for item in (extract_linkedin_item(r) for r in raw_list) if item]
    print(f"[{label}] raw={len(raw_list)} parsed={len(items)}")
    if raw_list and not items:
        print(f"[{label}] sample element: {json.dumps(raw_list[0])[:500]}")
    return items


BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
LINKEDIN_ID_PATTERN = re.compile(r"(\d{15,})")


def parse_company_post(li):
    link_tag = li.select_one("a.main-feed-card__overlay-link")
    link = link_tag.get("href") if link_tag else None
    article = li.select_one("article[data-activity-urn]")
    urn = article.get("data-activity-urn") if article else None
    if not link and urn:
        link = f"https://www.linkedin.com/feed/update/{urn}"
    id_source = f"{urn or ''} {link or ''}"
    id_match = LINKEDIN_ID_PATTERN.search(id_source)
    if not id_match:
        return None
    text_tag = li.select_one("p.attributed-text-segment-list__content")
    snippet = text_tag.get_text(strip=True) if text_tag else ""
    return {"id": id_match.group(1), "text": snippet, "url": link}


def fetch_linkedin_company():
    import bs4

    url = f"https://www.linkedin.com/company/{LINKEDIN_COMPANY}/"
    response = requests.get(
        url,
        headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"LinkedIn returned HTTP {response.status_code} (bot wall)")
    soup = bs4.BeautifulSoup(response.text, "lxml")
    items = []
    for li in soup.select("ul.updates__list > li"):
        item = parse_company_post(li)
        if item:
            items.append(item)
    print(f"[linkedin:company] page posts found={len(items)}")
    return items


def fetch_linkedin_profile():
    api = linkedin_client()
    posts = api.get_profile_posts(public_id=LINKEDIN_PROFILE, post_count=10)
    return parse_linkedin(posts, "linkedin:profile")


def x_message(item):
    return item["url"]


def linkedin_message(label):
    def format_item(item):
        snippet = item["text"].strip()
        if len(snippet) > 350:
            snippet = snippet[:350].rstrip() + "…"
        lines = [f"**New LinkedIn post — {label}**"]
        if snippet:
            lines.extend(["", snippet])
        lines.extend(["", item["url"]])
        return "\n".join(lines)
    return format_item


def process_source(state, key, fetch, format_message, failures):
    try:
        items = fetch()
    except Exception as exc:
        print(f"[{key}] fetch failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        failures.append(key)
        return
    items = [i for i in items if i.get("id") and str(i["id"]).isdigit()]
    if not items:
        print(f"[{key}] nothing found")
        return
    items.sort(key=lambda i: int(i["id"]))
    last_id = state.get(key)
    if not last_id:
        state[key] = items[-1]["id"]
        print(f"[{key}] first run: initialized at {items[-1]['id']}, nothing posted")
        return
    fresh = [i for i in items if int(i["id"]) > int(last_id)]
    if not fresh:
        print(f"[{key}] no new posts")
        return
    posted = fresh[:MAX_POSTS_PER_RUN]
    for item in posted:
        send_to_discord(format_message(item))
        time.sleep(1)
    state[key] = posted[-1]["id"]
    print(f"[{key}] posted {len(posted)} new post(s)")


def main():
    if not DISCORD_WEBHOOK:
        raise SystemExit("DISCORD_WEBHOOK env var is required")
    state = load_state()
    failures = []
    if TWITTER_AUTH_TOKEN:
        process_source(state, "x", fetch_x_posts, x_message, failures)
    else:
        print("[x] skipped: TWITTER_AUTH_TOKEN not set")
    if LINKEDIN_COMPANY:
        label = LINKEDIN_COMPANY
        process_source(state, "linkedin:company", fetch_linkedin_company, linkedin_message(label), failures)
    linkedin_cookie_ready = LINKEDIN_LI_AT and LINKEDIN_JSESSIONID
    if linkedin_cookie_ready and LINKEDIN_PROFILE:
        label = LINKEDIN_PROFILE
        process_source(state, "linkedin:profile", fetch_linkedin_profile, linkedin_message(label), failures)
    if LINKEDIN_PROFILE and not linkedin_cookie_ready:
        print("[linkedin:profile] skipped: LINKEDIN_LI_AT / LINKEDIN_JSESSIONID not set")
    save_state(state)
    if failures:
        sys.exit(f"failing sources: {', '.join(failures)}")
    print("done")


if __name__ == "__main__":
    main()
