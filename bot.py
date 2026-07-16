import json
import os
import re
import sys
import time

import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME", "heuresia")
LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT", "")
LINKEDIN_JSESSIONID = os.getenv("LINKEDIN_JSESSIONID", "")
LINKEDIN_COMPANY = os.getenv("LINKEDIN_COMPANY", "")
LINKEDIN_PROFILE = os.getenv("LINKEDIN_PROFILE", "")
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


def fetch_x_posts():
    from tweety import Twitter

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


def find_activity_id(obj):
    match = re.search(r"urn:li:activity:(\d+)", json.dumps(obj))
    return match.group(1) if match else None


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
    activity_id = find_activity_id(raw)
    if not activity_id:
        return None
    candidates = find_texts(raw)
    snippet = max(candidates, key=len) if candidates else ""
    return {
        "id": activity_id,
        "text": snippet,
        "url": f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}",
    }


def fetch_linkedin_company():
    api = linkedin_client()
    updates = api.get_company_updates(public_id=LINKEDIN_COMPANY, max_results=10)
    return [item for item in (extract_linkedin_item(u) for u in updates) if item]


def fetch_linkedin_profile():
    api = linkedin_client()
    posts = api.get_profile_posts(public_id=LINKEDIN_PROFILE, post_count=10)
    return [item for item in (extract_linkedin_item(p) for p in posts) if item]


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
    linkedin_ready = LINKEDIN_LI_AT and LINKEDIN_JSESSIONID
    if linkedin_ready and LINKEDIN_COMPANY:
        label = LINKEDIN_COMPANY
        process_source(state, "linkedin:company", fetch_linkedin_company, linkedin_message(label), failures)
    if linkedin_ready and LINKEDIN_PROFILE:
        label = LINKEDIN_PROFILE
        process_source(state, "linkedin:profile", fetch_linkedin_profile, linkedin_message(label), failures)
    if not linkedin_ready and (LINKEDIN_COMPANY or LINKEDIN_PROFILE):
        print("[linkedin] skipped: LINKEDIN_LI_AT / LINKEDIN_JSESSIONID not set")
    save_state(state)
    if failures:
        sys.exit(f"failing sources: {', '.join(failures)}")
    print("done")


if __name__ == "__main__":
    main()
