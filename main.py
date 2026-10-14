"""
Mediterranean Instagram bot v3

python main.py            build and post a carousel
python main.py dry        build everything but do NOT post (prints caption and image links)
python main.py insights   refresh post performance and print what is working
"""
import os
import re
import sys
import json
import time
import random
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google import genai
from google.genai import types

MODE = sys.argv[1] if len(sys.argv) > 1 else "post"
DRY = MODE == "dry"


def env(name, required=True):
    value = os.environ.get(name)
    if required and not value:
        sys.exit(f"Missing environment variable: {name}")
    return value


ACCESS_TOKEN = env("INSTAGRAM_ACCESS_TOKEN", MODE != "dry")
ACCOUNT_ID = env("INSTAGRAM_ACCOUNT_ID", MODE != "dry")
GEMINI_KEY = env("GEMINI_API_KEY", MODE != "insights")
UNSPLASH_KEY = env("UNSPLASH_ACCESS_KEY", MODE != "insights")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")  # verify this exists for your key
GRAPH = "https://graph.facebook.com/v26.0"

HISTORY_FILE = "history.json"
POOL_SIZE = 12            # photos Gemini judges per attempt
CAROUSEL_SIZE = 7         # max slides per post (Instagram allows 2 to 10)
MIN_SLIDES = 4
MIN_SLIDE_SCORE = 7       # slides scoring below this are dropped
MAX_PER_PHOTOGRAPHER = 3
MIN_W, MIN_H = 2000, 2500  # source photos must be bigger than the 1440 px we upload

# search term -> (display name, country, flag). Country and flag always come from here, never from the AI.
PLACES = {
    "Amalfi coast": ("Amalfi Coast", "Italy", "🇮🇹"),
    "Positano": ("Positano", "Italy", "🇮🇹"),
    "Capri": ("Capri", "Italy", "🇮🇹"),
    "Cinque Terre": ("Cinque Terre", "Italy", "🇮🇹"),
    "Sardinia": ("Sardinia", "Italy", "🇮🇹"),
    "Sicily coast": ("Sicily", "Italy", "🇮🇹"),
    "Santorini": ("Santorini", "Greece", "🇬🇷"),
    "Mykonos": ("Mykonos", "Greece", "🇬🇷"),
    "Crete": ("Crete", "Greece", "🇬🇷"),
    "Rhodes": ("Rhodes", "Greece", "🇬🇷"),
    "Bodrum": ("Bodrum", "Turkey", "🇹🇷"),
    "Antalya coast": ("Antalya", "Turkey", "🇹🇷"),
    "Fethiye": ("Fethiye", "Turkey", "🇹🇷"),
    "Kas Turkey": ("Kaş", "Turkey", "🇹🇷"),
    "Alanya": ("Alanya", "Turkey", "🇹🇷"),
    "French Riviera": ("French Riviera", "France", "🇫🇷"),
    "Corsica": ("Corsica", "France", "🇫🇷"),
    "Monaco": ("Monaco", "Monaco", "🇲🇨"),
    "Mallorca": ("Mallorca", "Spain", "🇪🇸"),
    "Menorca": ("Menorca", "Spain", "🇪🇸"),
    "Ibiza": ("Ibiza", "Spain", "🇪🇸"),
    "Costa Brava": ("Costa Brava", "Spain", "🇪🇸"),
    "Dubrovnik": ("Dubrovnik", "Croatia", "🇭🇷"),
    "Hvar": ("Hvar", "Croatia", "🇭🇷"),
    "Kotor": ("Kotor", "Montenegro", "🇲🇪"),
    "Malta": ("Malta", "Malta", "🇲🇹"),
    "Gozo": ("Gozo", "Malta", "🇲🇹"),
    "Cyprus": ("Cyprus", "Cyprus", "🇨🇾"),
}

# different search angles so the same place gives different photo sets each time
ANGLES = ["sunny", "sunny beach", "sunny village", "sunny harbor", "aerial sunny",
          "sunny old town", "sunny sea view", "sunny architecture"]

# words in Unsplash's photo description that signal a photo we do not want
BAD_WORDS = ("night", "dark", "rain", "storm", "fog", "overcast", "cloudy", "crowd", "snow", "winter")

HOOK_STYLES = {
    "question": "a short curious question",
    "claim": "a bold, confident claim or superlative about the place",
    "dream": "a dreamy, poetic fragment of two to five words",
    "sensory": "a vivid sensory line about a smell, sound or taste you would find there",
    "secret": "a line that hints at a local secret or something most visitors miss",
    "contrast": "a short contrast or surprise, two ideas set against each other",
    "invite": "a warm invitation or command that makes people want to go now",
    "story": "a tiny story opener, like the first line of a postcard",
}

BANNED_FIRST_WORDS = {"could", "is", "why", "ever", "imagine", "welcome", "discover"}

TITLE_LAYOUTS = {
    "classic": ["{place}, {country} ☀️ {flag}", "{hook}"],
    "hook_first": ["{hook}", "📍 {place}, {country} {flag}"],
    "flag_first": ["{flag} {place}, {country}", "{hook} ☀️"],
    "inline": ["{place}, {country} {flag} · {hook}"],
    "postcard": ["{hook} 🌊", "{place} · {country} {flag}"],
    "pin_last": ["{hook}"],
}

CTAS = [
    "Save this for your next trip 🌊",
    "Tag the person you'd bring here 👇",
    "Where should we go next? Tell me below 👇",
    "Send this to your travel buddy ✈️",
    "Would you stay here a week or a month? 👇",
    "Drop a ☀️ if this is on your list",
    "Bookmark this for your summer plans 🌴",
    "Which slide is your favorite? 👇",
    "Save it now, thank yourself later 🌅",
    "Double tap if you could live here 💙",
]

http = requests.Session()
# retries only safe GET requests, never POST, so a post can not be published twice
http.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))))

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None


# ---------------------------------------------------------------- text helpers
def clean(text):
    """No hyphens or dashes anywhere, as per the account style."""
    text = re.sub(r"\s*[\u2013\u2014]\s*|\s+-\s+", ", ", str(text or ""))
    return re.sub(r"\s+", " ", text.replace("-", " ")).strip()


# ---------------------------------------------------------------- history and learning
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
        json.dump(h, f, indent=1, ensure_ascii=False)


def used_photo_ids(h):
    return {pid for p in h["posts"] for pid in p.get("photo_ids", [])}


def rate(ins):
    """Saves, shares and comments per account reached. Saves and shares are what the algorithm rewards."""
    if not ins or not ins.get("reach"):
        return None
    return (ins.get("saved", 0) + ins.get("shares", 0) + 0.5 * ins.get("comments", 0)) / ins["reach"]


def choose(options, field, h, avoid_last=0, exclude=()):
    """Weighted random pick: skips recently used options and favors the ones that performed best."""
    options = list(options)
    recent = {p.get(field) for p in h["posts"][-avoid_last:]} if avoid_last else set()
    blocked = recent | set(exclude)
    pool = [o for o in options if o not in blocked] or options
    perf = {}
    for p in h["posts"]:
        r = rate(p.get("insights"))
        if r is not None and p.get(field) in pool:
            perf.setdefault(p[field], []).append(r)
    weights = [1.0 + (min(sum(perf[o]) / len(perf[o]) * 20, 3) if o in perf else 0) for o in pool]
    return random.choices(pool, weights=weights, k=1)[0]


# ---------------------------------------------------------------- photos
def crop_for_instagram(raw_url):
    # 4:5 portrait at 1440 px wide (Instagram's maximum), high JPEG quality
    return f"{raw_url}&w=1440&h=1800&fit=crop&crop=entropy&q=90&fm=jpg"


def search_unsplash(location, exclude):
    found = {}
    angle = random.choice(ANGLES)
    for page in random.sample(range(1, 6), 3):
        params = {
            "query": f"{location} {angle}",
            "orientation": "portrait",
            "content_filter": "high",
            "order_by": "relevant",
            "per_page": 30,
            "page": page,
            "client_id": UNSPLASH_KEY,
        }
        r = http.get("https://api.unsplash.com/search/photos", params=params, timeout=30)
        if r.status_code != 200:
            print(f"Unsplash returned {r.status_code}: {r.text[:200]}")
            continue
        for p in r.json().get("results", []):
            alt = (p.get("alt_description") or "").lower()
            if p["id"] in exclude or p["width"] < MIN_W or p["height"] < MIN_H:
                continue
            if any(w in alt for w in BAD_WORDS):
                continue
            found[p["id"]] = p
    photos = sorted(found.values(), key=lambda p: p.get("likes", 0), reverse=True)[:40]
    random.shuffle(photos)
    return photos[:POOL_SIZE]


def ping_unsplash_download(photo):
    # Required by the Unsplash API guidelines whenever a photo is actually used
    try:
        http.get(photo["links"]["download_location"], params={"client_id": UNSPLASH_KEY}, timeout=15)
    except Exception as e:
        print(f"Download ping warning: {e}")


def select_slides(photos, scores):
    ranked = sorted(zip(scores, photos), key=lambda x: x[0], reverse=True)  # best photo becomes the cover
    keep, per_photographer = [], {}
    for score, photo in ranked:
        if score < MIN_SLIDE_SCORE:
            break
        who = photo["user"]["username"]
        if per_photographer.get(who, 0) >= MAX_PER_PHOTOGRAPHER:
            continue
        per_photographer[who] = per_photographer.get(who, 0) + 1
        keep.append(photo)
        if len(keep) == CAROUSEL_SIZE:
            break
    return keep


# ---------------------------------------------------------------- AI editor
EDITOR_PROMPT = """You are the editor of a Mediterranean travel Instagram account.
You get {n} photos found by searching "{location}", numbered 0 to {last} in order.

Return ONLY JSON with these keys:
- scores: list of {n} numbers (1 to 10), one per photo in order. High means bright, sunny, happy, razor sharp,
  clean, well composed and scroll stopping. Judge technical quality at this resolution and penalize blur,
  noise, over sharpening, heavy HDR or filters, tilted horizons, a low resolution phone look, haze, overcast
  sky, crowds, clutter, visible text or logos, and photos that do not show the same region as the others.
- place_confident: true only if most of the good photos clearly show one specific named place
- place: that specific place (city, island or village)
- hook: {hook_style}. 3 to 9 words. It must NOT be a question unless the style says so. Never start with
  Could, Is, Why, Ever, Imagine, Welcome or Discover. Make it specific to this place. No hyphens or dashes.
- description: 2 to 3 short sentences, 45 words maximum, painting a vivid picture of the place: what you
  would see, smell or taste there, plus one surprising or useful detail. Only include details you are
  confident are true. Do not start with the place name. No hyphens or dashes.
- tip: one short practical travel tip (best months, a local dish, how to get there), or an empty string if
  you are not sure. No hyphens or dashes.
- hashtags: 3 to 4 relevant lowercase hashtags including the #

Be fresh. Do NOT reuse or closely echo any of these recent hooks and openings: {recent}{note}
"""


def validate_editor_output(d, n, style, h):
    """Enforce the rules in code, because prompts alone get ignored."""
    scores = d.get("scores")
    if not isinstance(scores, list) or len(scores) != n:
        raise ValueError(f"scores must be a list of exactly {n} numbers")
    d["scores"] = [float(s) for s in scores]
    for key in ("place", "hook", "description"):
        if not str(d.get(key, "")).strip():
            raise ValueError(f"missing {key}")
    tags = [re.sub(r"[^\w]", "", str(t)) for t in (d.get("hashtags") or [])]
    tags = ["#" + t for t in tags if t][:4]
    if not tags:
        raise ValueError("hashtags must be a non empty list")
    d["hashtags"] = tags

    hook = clean(d["hook"])
    words = hook.lower().split()
    if style != "question" and hook.endswith("?"):
        raise ValueError("the hook must not be a question")
    if words and words[0] in BANNED_FIRST_WORDS:
        raise ValueError(f"the hook must not start with the word {words[0]}")
    for p in h["posts"][-10:]:
        old = (p.get("hook") or "").lower().split()
        if old[:2] and old[:2] == words[:2]:
            raise ValueError("the hook starts like a recent hook")
    opening = " ".join(clean(d["description"]).lower().split()[:3])
    if any(opening == (p.get("opening") or "").lower() for p in h["posts"][-10:]):
        raise ValueError("the description opens like a recent one")


def edit_with_gemini(photos, location, style, h):
    images, usable = [], []
    for p in photos:
        try:
            r = http.get(p["urls"]["regular"], timeout=30)  # 1080 px wide, so quality problems are visible
            r.raise_for_status()
            images.append(r.content)
            usable.append(p)
        except Exception as e:
            print(f"Skipping photo {p['id']}: {e}")
    if len(usable) < MIN_SLIDES:
        raise ValueError("not enough downloadable photos")

    base = []
    for i, img in enumerate(images):
        base += [f"Photo {i}:", types.Part.from_bytes(data=img, mime_type="image/jpeg")]
    recent = [p.get("hook", "") for p in h["posts"][-8:]] + [p.get("opening", "") for p in h["posts"][-8:]]
    recent = "; ".join(r for r in recent if r) or "none"

    note = ""
    for attempt in range(4):
        prompt = EDITOR_PROMPT.format(n=len(usable), last=len(usable) - 1, location=location,
                                      hook_style=HOOK_STYLES[style], recent=recent, note=note)
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=base + [prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.text.strip())
            d = json.loads(text)
            validate_editor_output(d, len(usable), style, h)
            return d, usable
        except (ValueError, TypeError, KeyError) as e:
            print(f"Gemini output rejected (attempt {attempt + 1}/4): {e}")
            note = f"\nYour previous answer was rejected because: {e}. Fix that."
        except Exception as e:
            print(f"Gemini API error (attempt {attempt + 1}/4): {e}")
            time.sleep(20)
    raise Exception("Gemini failed after 4 attempts")


def build_post(h):
    used = used_photo_ids(h)
    style = choose(HOOK_STYLES, "style", h, avoid_last=2)
    tried = []
    for _ in range(4):
        location = choose(PLACES, "location", h, avoid_last=12, exclude=tried)
        tried.append(location)
        print(f"Trying {location} with the '{style}' hook style")
        photos = search_unsplash(location, used)
        if len(photos) < MIN_SLIDES:
            print(f"Only {len(photos)} usable photos, trying another place")
            continue
        try:
            d, photos = edit_with_gemini(photos, location, style, h)
        except ValueError as e:
            print(f"{e}, trying another place")
            continue
        chosen = select_slides(photos, d["scores"])
        print(f"Scores {sorted(d['scores'], reverse=True)} -> {len(chosen)} slides qualify")
        if len(chosen) >= MIN_SLIDES:
            return location, style, d, chosen
    raise Exception("Could not assemble a good enough carousel")


def build_caption(d, location, h):
    name, country, flag = PLACES[location]
    confident = d.get("place_confident") in (True, "true", "True")
    place = clean(d["place"]) if confident else name
    layout = choose(TITLE_LAYOUTS, "layout", h, avoid_last=3)
    cta = choose(CTAS, "cta", h, avoid_last=4)
    hook = clean(d["hook"])
    description = clean(d["description"])

    fields = {"place": place, "country": country, "flag": flag, "hook": hook}
    lines = [t.format(**fields) for t in TITLE_LAYOUTS[layout]]
    lines += ["", description]
    tip = clean(d.get("tip"))
    if tip:
        lines += ["", f"💡 {tip}"]
    if layout == "pin_last":
        lines += ["", f"📍 {place}, {country} {flag}"]
    lines += ["", cta, "", " ".join(d["hashtags"])]

    meta = {"place": place, "country": country, "layout": layout, "cta": cta, "hook": hook,
            "opening": " ".join(description.lower().split()[:3])}
    return "\n".join(lines), meta


# ---------------------------------------------------------------- instagram
def graph(method, path, **params):
    params["access_token"] = ACCESS_TOKEN
    kwargs = {"params": params} if method == "GET" else {"data": params}
    r = http.request(method, f"{GRAPH}/{path}", timeout=60, **kwargs)
    try:
        out = r.json()
    except ValueError:
        out = {"error": {"message": r.text[:200]}}
    err = out.get("error") if isinstance(out, dict) else None
    if err and err.get("code") == 190:
        print("!! Instagram access token is expired or invalid. Create a new one and update the GitHub secret.")
    return out


def graph_get(path, **params):
    return graph("GET", path, **params)


def graph_post(path, **params):
    return graph("POST", path, **params)


def wait_until_ready(container_id):
    for _ in range(40):
        status = graph_get(container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise Exception(f"Container {container_id} ended with status {status}")
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


def create_child(image_url, alt):
    data = {"image_url": image_url, "is_carousel_item": "true"}
    if alt:  # alt text helps accessibility and search; fall back if the API rejects it
        res = graph_post(f"{ACCOUNT_ID}/media", alt_text=alt, **data)
        if "id" in res:
            return res["id"]
        print(f"alt_text rejected, retrying without it: {res.get('error', {}).get('message')}")
    res = graph_post(f"{ACCOUNT_ID}/media", **data)
    if "id" not in res:
        raise Exception(f"Child container failed: {res}")
    return res["id"]


def post_carousel(image_urls, alts, caption, geo_query):
    child_ids = [create_child(u, a) for u, a in zip(image_urls, alts)]
    for cid in child_ids:
        wait_until_ready(cid)

    payload = {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption}
    loc_id = get_facebook_location_id(geo_query)
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


def post_first_comment(media_id, text):
    res = graph_post(f"{media_id}/comments", message=text)
    if "id" not in res:
        print(f"First comment skipped: {res.get('error', {}).get('message')}")


# ---------------------------------------------------------------- main flows
def run_post():
    h = load_history()
    print(f"History: {len(h['posts'])} posts, {len(used_photo_ids(h))} photos already used")
    location, style, d, chosen = build_post(h)
    caption, meta = build_caption(d, location, h)

    images = [crop_for_instagram(p["urls"]["raw"]) for p in chosen]
    alts = [((p.get("alt_description") or "")[:1].upper() + (p.get("alt_description") or "")[1:])[:400]
            for p in chosen]
    names = list(dict.fromkeys(p["user"].get("name") or p["user"]["username"] for p in chosen))
    credit = "📷 Photos by " + ", ".join(names) + " on Unsplash"

    print("\n" + caption + "\n")
    print(credit)
    if DRY:
        print("\nDRY RUN, nothing posted. Slide links:")
        for u in images:
            print(u)
        return

    for p in chosen:
        ping_unsplash_download(p)
    media_id = post_carousel(images, alts, caption, f"{meta['place']} {meta['country']}")
    print(f"Published {media_id}")

    h["posts"].append({
        "media_id": media_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "location": location,
        "place": meta["place"],
        "style": style,
        "hook": meta["hook"],
        "opening": meta["opening"],
        "cta": meta["cta"],
        "layout": meta["layout"],
        "photo_ids": [p["id"] for p in chosen],
        "insights": None,
    })
    save_history(h)           # saved before the comment, so a comment failure can never cause a repost
    post_first_comment(media_id, credit)


METRIC_SETS = ["reach,saved,shares,likes,comments", "reach,saved,likes,comments", "reach,likes"]


def fetch_insights(media_id):
    message = None
    for metrics in METRIC_SETS:
        res = graph_get(f"{media_id}/insights", metric=metrics)
        if "data" in res:
            out = {}
            for m in res["data"]:
                value = (m.get("values") or [{}])[0].get("value")
                if value is None:
                    value = (m.get("total_value") or {}).get("value", 0)
                out[m["name"]] = value
            return out
        message = res.get("error", {}).get("message")
    print(f"Insights unavailable for {media_id}: {message}")
    return None


def run_insights():
    h = load_history()
    now = datetime.now(timezone.utc)
    for p in h["posts"]:
        age_h = (now - datetime.fromisoformat(p["ts"])).total_seconds() / 3600
        if age_h < 24 or (p.get("insights") and age_h > 24 * 7):
            continue  # too fresh to measure, or already final
        ins = fetch_insights(p["media_id"])
        if ins:
            p["insights"] = ins
            print(p.get("place"), p.get("style"), ins)
    save_history(h)

    for field in ("style", "location", "layout", "cta"):
        groups = {}
        for p in h["posts"]:
            r = rate(p.get("insights"))
            if r is not None and p.get(field):
                groups.setdefault(p[field], []).append(r)
        if groups:
            print(f"\nBest {field} (saves + shares + comments per reach)")
            for k, v in sorted(groups.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
                print(f"  {k}: {sum(v) / len(v):.2%} over {len(v)} posts")


if __name__ == "__main__":
    if MODE == "insights":
        run_insights()
    else:
        run_post()
