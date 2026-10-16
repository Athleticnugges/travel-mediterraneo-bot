import os
import time
import random
import requests
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
COVERR_KEY = os.environ["COVERR_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GRAPH = "https://graph.facebook.com/v26.0"

PLACES = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Sardinia", 
    "Santorini", "Mykonos", "Crete", "Bodrum", "Antalya", "Fethiye", 
    "French Riviera", "Corsica", "Monaco", "Mallorca", "Ibiza", 
    "Dubrovnik", "Malta", "Cyprus"
]

def get_vertical_video():
    headers = {"Authorization": f"Bearer {COVERR_KEY}"}
    
    for _ in range(5):
        location = random.choice(PLACES)
        url = f"https://api.coverr.co/videos?query={location}&urls=true"
        res = requests.get(url, headers=headers).json()
        
        if "error" in res:
            print(f"Coverr API Warning: {res}")
            continue
            
        # Strictly enforce vertical aspect ratio using raw file dimensions
        hits = res.get("hits", [])
        vertical_hits = [h for h in hits if h.get("width", 1) < h.get("height", 0)]
        
        if vertical_hits:
            chosen = random.choice(vertical_hits)
            urls = chosen.get("urls", {})
            video_url = urls.get("mp4_download") or urls.get("mp4")
            if video_url:
                return video_url, location

    # Guaranteed vertical fallback if specific locations lack portrait footage
    fallback_url = "https://api.coverr.co/videos?query=mediterranean+beach+vertical&urls=true"
    f_res = requests.get(fallback_url, headers=headers).json()
    f_hits = [h for h in f_res.get("hits", []) if h.get("width", 1) < h.get("height", 0)]
    
    if f_hits:
        chosen = random.choice(f_hits)
        video_url = chosen["urls"].get("mp4_download") or chosen["urls"].get("mp4")
        if video_url:
            return video_url, "Mediterranean Sea"

    raise Exception("Could not find a vertical video on Coverr. Verify your COVERR_API_KEY is correct.")

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
            print(f"Gemini API attempt {attempt + 1}/4 failed: {e}")
            if attempt < 3:
                time.sleep(30)
            else:
                raise Exception("Gemini API failed after 4 attempts.") from e

def wait_until_ready(container_id):
    print("Waiting for Meta servers to process vertical video file...")
    for _ in range(60):
        url = f"{GRAPH}/{container_id}?fields=status_code&access_token={ACCESS_TOKEN}"
        res = requests.get(url).json()
        status = res.get("status_code")
        
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise Exception(f"Container {container_id} ended with status {status}: {res}")
        
        time.sleep(10)
    raise Exception(f"Container {container_id} processing timed out")

def post_reel(video_url, caption):
    print("Creating Reels media container on Meta Graph API...")
    container_url = f"{GRAPH}/{ACCOUNT_ID}/media"
    payload = {
        'media_type': 'REELS',
        'video_url': video_url,
        'caption': caption,
        'access_token': ACCESS_TOKEN
    }
    
    res = requests.post(container_url, data=payload).json()
    creation_id = res.get('id')
    if not creation_id:
        raise Exception(f"Failed to create media container: {res}")

    wait_until_ready(creation_id)

    print("Publishing Reel to Instagram...")
    publish_url = f"{GRAPH}/{ACCOUNT_ID}/media_publish"
    publish_payload = {
        'creation_id': creation_id,
        'access_token': ACCESS_TOKEN
    }
    
    pub_res = requests.post(publish_url, data=publish_payload).json()
    if 'id' not in pub_res:
        raise Exception(f"Failed to publish Reel: {pub_res}")
    
    return pub_res['id']

def run():
    print("Fetching strictly vertical (9:16) video from Coverr...")
    video_url, location = get_vertical_video()
    print(f"Selected 9:16 Video Stream: {video_url}")
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    reel_id = post_reel(video_url, caption)
    print(f"Successfully published Reel ID: {reel_id}")

if __name__ == "__main__":
    run()
