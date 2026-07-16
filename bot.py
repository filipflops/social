import os
import requests
from tweety import Twitter

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
TWITTER_AUTH_TOKEN = os.getenv("TWITTER_AUTH_TOKEN")
TWITTER_USERNAME = "heuresia"

app = Twitter("session")
app.load_auth_token(TWITTER_AUTH_TOKEN)

tweets = app.get_tweets(TWITTER_USERNAME)
if not tweets:
    print("Brak tweetów lub błąd pobierania.")
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
        "avatar_url": "https://twoja_strona.com/logo.png",
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
    print("Wysłano nowy Tweet na Discorda!")
else:
    print("Brak nowych tweetów.")