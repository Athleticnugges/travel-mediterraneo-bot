import os
import time
import random
import requests
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GRAPH = "https://graph.facebook.com/v26.0"

PLACES = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Sardinia", 
    "Santorini", "Mykonos", "Crete", "Bodrum", "Antalya", "Fethiye", 
    "French Riviera", "Corsica", "Monaco", "Mallorca", "Ibiza", 
    "Dubrovnik", "Malta", "Cyprus"
]

def get_pixabay_video():
    for _ in range(3):
        location = random.choice(PLACES)
        url = "https://pixabay.com/api/videos/"
        params = {
            "key": PIXABAY_KEY,
            "q": f"{location} sunny beach",
            "video_type": "film",
            "per_page": 20
        }
        
        res = requests.get(url, params=params).json()
        hits = res.get("hits", [])
        
        if hits:
            # Prefer vertical orientations where height > width
            vertical_hits = [
                h for h in hits 
                if h["videos"].get("medium", {}).get("height", 0) > h["videos"].get("medium", {}).get("width", 0)
            ]
            chosen = random.choice(vertical_hits) if vertical_hits else random.choice(hits)
            
            # Fetch medium stream (1920x1080) or small stream (1280x720)
            v_data = chosen["videos"]
            video_url = v_data.get("medium", {}).get("url") or v_data.get("small", {}).get("url")
            
            if video_url:
                return video_url, location

    raise Exception("Could not find a valid video on Pixabay.")

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
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    return response.text.strip().replace("-", " ").replace("  ", " ")

def wait_until_ready(container_id):
    print("Waiting for Meta servers to process the video container...")
    for _ in range(40):
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
    print("Fetching Mediterranean video from Pixabay...")
    video_url, location = get_pixabay_video()
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    reel_id = post_reel(video_url, caption)
    print(f"Successfully published Reel ID: {reel_id}")

if __name__ == "__main__":
    run()
