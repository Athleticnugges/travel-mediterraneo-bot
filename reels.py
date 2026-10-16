import os
import time
import random
import requests
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GRAPH = "https://graph.facebook.com/v21.0"

PLACES = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Sardinia",
    "Santorini", "Mykonos", "Crete", "Bodrum", "Antalya", "Fethiye",
    "French Riviera", "Corsica", "Monaco", "Mallorca", "Ibiza",
    "Dubrovnik", "Malta", "Cyprus"
]

def is_good_reel_video(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    if height <= width:
        return False
    if width < 720 or width > 1920:
        return False
    ratio = width / height
    return 0.50 <= ratio <= 0.62

def get_vertical_video():
    headers = {"Authorization": PEXELS_KEY} if PEXELS_KEY else {}

    for attempt in range(8):
        location = random.choice(PLACES)
        url = (
            f"https://api.pexels.com/videos/search"
            f"?query={location}&orientation=portrait&per_page=20&size=medium"
        )
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            videos = res.json().get("videos", [])
        except Exception as e:
            print(f"Pexels attempt {attempt+1} failed: {e}")
            continue

        for video in videos:
            w = video.get("width", 0)
            h = video.get("height", 0)
            if not is_good_reel_video(w, h):
                continue

            video_files = video.get("video_files", [])
            video_files = sorted(
                [f for f in video_files if f.get("file_type") == "video/mp4"],
                key=lambda f: f.get("width", 0),
                reverse=True,
            )

            for f in video_files:
                fw, fh = f.get("width", 0), f.get("height", 0)
                if is_good_reel_video(fw, fh):
                    return f["link"], location

    if PIXABAY_KEY:
        print("Trying Pixabay fallback…")
        pb_url = (
            f"https://pixabay.com/api/videos/"
            f"?key={PIXABAY_KEY}&q=mediterranean+coast&video_type=film&per_page=20"
        )
        try:
            hits = requests.get(pb_url, timeout=15).json().get("hits", [])
            for hit in hits:
                videos_dict = hit.get("videos", {})
                for quality in ("large", "medium", "small"):
                    v = videos_dict.get(quality, {})
                    w, h = v.get("width", 0), v.get("height", 0)
                    if is_good_reel_video(w, h) and v.get("url"):
                        return v["url"], "Mediterranean Coast"
        except Exception as e:
            print(f"Pixabay error: {e}")

    raise Exception("Could not find a suitable 9:16 vertical video")

def generate_caption(location):
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
Generate a minimalist Instagram Reel caption for the Mediterranean location: {location}.
CRITICAL INSTRUCTIONS:
Output EXACTLY this format and nothing else.
1. Line 1: [Specific Island/City Name], [Country] ☀️ [Country Flag Emoji]
2. Line 2: Exactly ONE short, interesting sentence sharing a random fact about the location.
3. Line 3: A blank line.
4. Line 4: Exactly 3 to 4 hashtags.
DO NOT USE HYPHENS ("-") OR DASHES ANYWHERE.
"""
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return response.text.strip().replace("-", " ").replace("  ", " ")
        except Exception as e:
            print(f"Gemini attempt {attempt+1}/4 failed: {e}")
            if attempt < 3:
                time.sleep(20)
            else:
                raise

def wait_until_ready(container_id):
    print("Waiting for Meta to process the video…")
    for _ in range(60):
        url = f"{GRAPH}/{container_id}?fields=status_code&access_token={ACCESS_TOKEN}"
        res = requests.get(url, timeout=10).json()
        status = res.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise Exception(f"Container failed: {res}")
        time.sleep(8)
    raise Exception("Processing timed out")

def post_reel(video_url, caption):
    print("Creating Reels container…")
    container_url = f"{GRAPH}/{ACCOUNT_ID}/media"
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": ACCESS_TOKEN,
    }
    res = requests.post(container_url, data=payload, timeout=30).json()
    creation_id = res.get("id")
    if not creation_id:
        raise Exception(f"Failed to create container: {res}")

    wait_until_ready(creation_id)

    print("Publishing Reel…")
    publish_url = f"{GRAPH}/{ACCOUNT_ID}/media_publish"
    pub_res = requests.post(
        publish_url,
        data={"creation_id": creation_id, "access_token": ACCESS_TOKEN},
        timeout=30,
    ).json()

    if "id" not in pub_res:
        raise Exception(f"Failed to publish: {pub_res}")
    return pub_res["id"]

def run():
    print("Looking for a good 9:16 vertical video…")
    video_url, location = get_vertical_video()
    print(f"Selected video → {video_url}")
    print(f"Location → {location}")

    caption = generate_caption(location)
    print(f"Caption:\n{caption}\n")

    reel_id = post_reel(video_url, caption)
    print(f"✅ Successfully published Reel ID: {reel_id}")

if __name__ == "__main__":
    run()
