"""
Mediterranean Instagram bot v2

python main.py            -> pick best photos, post a carousel
python main.py insights   -> pull performance for recent posts and print what works
"""
import os
import re
import sys
import json
import time
import random
import requests
from datetime import datetime, timezone
from google import genai
from google.genai import types

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
UNSPLASH_KEY = os.environ["UNSPLASH_ACCESS_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # verify this exists for your key
GRAPH = "https://graph.facebook.com/v26.0"

HISTORY_FILE = "history.json"
POOL_SIZE = 10          # photos shown to Gemini in one call
CAROUSEL_SIZE = 6       # slides per post (Instagram allows 2 to 10)
MIN_SLIDE_SCORE = 7     # slides below this are dropped
MIN_SLIDES = 3

SEARCH_TERMS = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Santorini", "Mykonos",
    "Bodrum", "Antalya coast", "Fethiye", "Kas Turkey", "French Riviera",
    "Mallorca", "Menorca", "Ibiza", "Corsica", "Sardinia", "Sicily coast",
    "Dubrovnik", "Hvar", "Kotor", "Malta", "Gozo", "Cyprus", "Costa Brava", "Algarve",
]

HOOK_STYLES = {
    "question": "a short question that makes people curious (example: Could this be Europe's bluest bay?)",
    "claim": "a bold, confident claim (example: Italy's most underrated coastline)",
    "dream": "a dreamy two to five word line (example: Salt air, golden hours)",
}

client = genai.Client(api_key=GEMINI_KEY)


# ---------------------------------------------------------------- history
def load_history():
    try:
        with open(HISTORY_FILE) as f:
            h = json.load(f)
    except Exception:
        h = {}
    h.setdefault("posts", [])
    return h


def save_history(h):
    with open(HISTORY_FILE, "w") as f:
        json.dump(h, f, indent=1)


def used_photo_ids(h):
    return {pid for p in h["posts"] for pid in p.get("photo_ids", [])}


def pick_location(h):
    """Weighted random: avoid recent places, favor places whose posts earned more saves and shares."""
    recent = [p["location"] for p in h["posts"][-12:]]
    stats = {}
    for p in h["posts"]:
        ins = p.get("insights")
        if ins and ins.get("reach"):
            rate = (ins.get("saved", 0) + ins.get("shares", 0)) / ins["reach"]
            stats.setdefault(p["location"], []).append(rate)
    weights = []
    for loc in SEARCH_TERMS:
        w = 0.0 if loc in recent else 1.0
        if loc in stats:
            avg = sum(stats[loc]) / len(stats[loc])
            w *= 1 + min(avg * 20, 3)
        weights.append(w)
    if sum(weights) == 0:
        weights = [1.0] * len(SEARCH_TERMS)
    return random.choices(SEARCH_TERMS, weights=weights, k=1)[0]


def pick_hook_style(h):
    """Rotate through styles evenly until there is data, then lean toward the best performer."""
    perf = {}
    for p in h["posts"]:
        ins = p.get("insights")
        if p.get("style") and ins and ins.get("reach"):
            perf.setdefault(p["style"], []).append((ins.get("saved", 0) + ins.get("shares", 0)) / ins["reach"])
    counts = {s: sum(1 for p in h["posts"] if p.get("style") == s) for s in HOOK_STYLES}
    if len(perf) < len(HOOK_STYLES) or min(len(v) for v in perf.values()) < 3:
        return min(counts, key=counts.get)           # explore
    if random.random() < 0.2:
        return random.choice(list(HOOK_STYLES))      # keep exploring a little
    return max(perf, key=lambda s: sum(perf[s]) / len(perf[s]))


# ---------------------------------------------------------------- photos
def crop_for_instagram(raw_url):
    return f"{raw_url}&w=1080&h=1350&fit=crop&crop=entropy&q=85&fm=jpg"


def search_unsplash(location, exclude):
    found = {}
    for page in random.sample(range(1, 6), 3):
        params = {
            "query": f"{location} sunny",
            "orientation": "portrait",
            "content_filter": "high",
            "order_by": "relevant",
            "per_page": 30,
            "page": page,
            "client_id": UNSPLASH_KEY,
        }
        r = requests.get("https://api.unsplash.com/search/photos", params=params, timeout=30)
        if r.status_code != 200:
            print(f"Unsplash returned {r.status_code}: {r.text[:200]}")
            continue
        for p in r.json().get("results", []):
            if p["id"] not in exclude and p["width"] >= 1600:
                found[p["id"]] = p
    photos = sorted(found.values(), key=lambda p: p.get("likes", 0), reverse=True)[:30]
    random.shuffle(photos)
    return photos[:POOL_SIZE]


def ping_unsplash_download(photo):
    try:
        requests.get(photo["links"]["download_location"], params={"client_id": UNSPLASH_KEY}, timeout=15)
    except Exception as e:
        print(f"Download ping warning: {e}")


# ---------------------------------------------------------------- AI editor
EDITOR_PROMPT = """You are the editor of a Mediterranean travel Instagram account.
You get {n} photos found by searching "{location}", numbered 0 to {last} in order.

Return ONLY JSON with these keys:
- scores: list of {n} integers (1 to 10), one per photo in order. High means bright, sunny, happy,
  sharp, well composed, scroll stopping. Penalize haze, overcast sky, crowds, clutter, heavy filters,
  visible text or logos, and photos that clearly do not show the same region as the others.
- place: the most specific place shown by most of the good photos (city, island or village),
  or the search term if unsure
- country: its country
- flag: country flag emoji
- hook: {hook_style}. 3 to 8 words. No hyphens or dashes.
- fact: ONE short sentence about the place. Only state something you are highly confident is true;
  if unsure, write a short evocative observation instead. No hyphens or dashes.
- hashtags: 3 to 4 relevant lowercase hashtags including the #
"""


def edit_with_gemini(photos, location, hook_style):
    parts = []
    for i, p in enumerate(photos):
        img = requests.get(p["urls"]["small"], timeout=30).content
        parts.append(f"Photo {i}:")
        parts.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))
    parts.append(EDITOR_PROMPT.format(
        n=len(photos), last=len(photos) - 1, location=location, hook_style=HOOK_STYLES[hook_style]))
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            data = json.loads(resp.text)
            if len(data["scores"]) != len(photos):
                raise ValueError("score count mismatch")
            return data
        except Exception as e:
            print(f"Gemini error (attempt {attempt + 1}/3): {e}")
            time.sleep(20)
    raise Exception("Gemini failed after 3 attempts")


def clean(text):
    return re.sub(r"\s*[\u2013\u2014]\s*|\s+-\s+", ", ", text).strip()


def build_caption(d):
    return "\n".join([
        f"{d['place']}, {d['country']} ☀️ {d['flag']}",
        clean(d["hook"]),
        "",
        clean(d["fact"]),
        "",
        "Save this for your next trip 🌊 Send it to who you'd go with 👇",
        "",
        " ".join(d["hashtags"][:4]),
    ])


# ---------------------------------------------------------------- instagram
def graph_get(path, **params):
    params["access_token"] = ACCESS_TOKEN
    return requests.get(f"{GRAPH}/{path}", params=params, timeout=30).json()


def graph_post(path, **data):
    data["access_token"] = ACCESS_TOKEN
    return requests.post(f"{GRAPH}/{path}", data=data, timeout=60).json()


def wait_until_ready(container_id):
    for _ in range(30):
        status = graph_get(container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise Exception(f"Container {container_id} status {status}")
        time.sleep(3)
    raise Exception(f"Container {container_id} timed out")


def get_facebook_location_id(query):
    try:
        res = graph_get("pages/search", q=query, fields="id,name,location")
        for page in res.get("data", []):
            if "location" in page:
                return page["id"]
    except Exception as e:
        print(f"Location search warning: {e}")
    return None


def post_carousel(image_urls, caption, place):
    child_ids = []
    for url in image_urls:
        res = graph_post(f"{ACCOUNT_ID}/media", image_url=url, is_carousel_item="true")
        if "id" not in res:
            raise Exception(f"Child container failed: {res}")
        child_ids.append(res["id"])
    for cid in child_ids:
        wait_until_ready(cid)

    payload = {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption}
    loc_id = get_facebook_location_id(place)
    if loc_id:
        payload["location_id"] = loc_id
    parent = graph_post(f"{ACCOUNT_ID}/media", **payload)
    if "id" not in parent:
        raise Exception(f"Carousel container failed: {parent}")
    wait_until_ready(parent["id"])

    out = graph_post(f"{ACCOUNT_ID}/media_publish", creation_id=parent["id"])
    if "id" not in out:
        raise Exception(f"Publish failed: {out}")
    return out["id"]


def run_post():
    h = load_history()
    used = used_photo_ids(h)
    print("History:", len(h["posts"]), "posts,", len(used), "photos already used")
    style = pick_hook_style(h)

    for attempt in range(4):
        location = pick_location(h)
        print(f"Trying {location} with '{style}' hook")
        photos = search_unsplash(location, used)
        if len(photos) < MIN_SLIDES:
            continue
        d = edit_with_gemini(photos, location, style)
        ranked = sorted(zip(d["scores"], photos), key=lambda x: x[0], reverse=True)
        keep = [(s, p) for s, p in ranked if s >= MIN_SLIDE_SCORE][:CAROUSEL_SIZE]
        print(f"Scores: {sorted(d['scores'], reverse=True)} -> keeping {len(keep)}")
        if len(keep) >= MIN_SLIDES:
            break
    else:
        raise Exception("Could not assemble a good enough carousel")

    chosen = [p for _, p in keep]
    for p in chosen:
        ping_unsplash_download(p)

    caption = build_caption(d)
    print(caption)
    media_id = post_carousel([crop_for_instagram(p["urls"]["raw"]) for p in chosen], caption, d["place"])
    print(f"Published {media_id}")

    h["posts"].append({
        "media_id": media_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "location": location,
        "place": d["place"],
        "style": style,
        "photo_ids": [p["id"] for p in chosen],
        "insights": None,
    })
    save_history(h)


# ---------------------------------------------------------------- insights
def run_insights():
    h = load_history()
    now = datetime.now(timezone.utc)
    for p in h["posts"]:
        age_h = (now - datetime.fromisoformat(p["ts"])).total_seconds() / 3600
        if age_h < 24 or (p.get("insights") and age_h > 24 * 7):
            continue  # too fresh, or already final
        res = graph_get(f"{p['media_id']}/insights", metric="reach,saved,shares,likes,comments")
        if "data" not in res:
            print(f"Insights unavailable for {p['media_id']}: {res.get('error', {}).get('message')}")
            continue
        p["insights"] = {m["name"]: m["values"][0]["value"] for m in res["data"]}
        print(p["place"], p["style"], p["insights"])
    save_history(h)

    by_style, by_loc = {}, {}
    for p in h["posts"]:
        ins = p.get("insights")
        if ins and ins.get("reach"):
            rate = (ins.get("saved", 0) + ins.get("shares", 0)) / ins["reach"]
            by_style.setdefault(p["style"], []).append(rate)
            by_loc.setdefault(p["location"], []).append(rate)
    for title, groups in (("Hook style", by_style), ("Location", by_loc)):
        print(f"\n{title}: average (saves + shares) / reach")
        for k, v in sorted(groups.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
            print(f"  {k}: {sum(v) / len(v):.3%} over {len(v)} posts")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "insights":
        run_insights()
    else:
        run_post()
