import os
import requests
from tweety import Twitter

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN")
TWITTER_USERNAME = "heuresia"

app = Twitter("session")
app.load_auth_token(TWITTER_AUTH_TOKEN)

search_results = app.search(f"from:{TWITTER_USERNAME}")
tweets = list(search_results)

if not tweets:
    print("No tweets found or fetch error.")
    exit()

latest_tweet = tweets[0]
tweet_id = latest_tweet.id
tweet_url = f"https://fxtwitter.com/{TWITTER_USERNAME}/status/{tweet_id}"

db_file = "last_tweet.txt"
last_sent_id = ""

if os.path.exists(db_file):
    with open(db_file, "r") as f:
        last_sent_id = f.read().strip()

if str(tweet_id) != last_sent_id:
    payload = {
        "username": "Heuresia Socials",
        "avatar_url": "https://media.discordapp.net/attachments/1260654667608621177/1526930523560087793/heuresia-1c-mark-dark.png?ex=6a5a21dd&is=6a58d05d&hm=c6e593c26c77066dbb8f5fabc1ab087601d83011162e4f34effb101af412cd34&=&format=webp&quality=lossless&width=857&height=857",
        "content": tweet_url
    }
    requests.post(DISCORD_WEBHOOK, json=payload)
    
    with open(db_file, "w") as f:
        f.write(str(tweet_id))
    
    os.system('git config --global user.name "Heuresia Bot"')
    os.system('git config --global user.email "bot@heuresia.com"')
    os.system('git add last_tweet.txt')
    os.system('git commit -m "chore: update last sent tweet ID"')
    os.system('git push')
    print("New tweet sent to Discord!")
else:
    print("No new tweets.")