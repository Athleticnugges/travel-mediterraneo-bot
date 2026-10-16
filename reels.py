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
    for _ in range(10):
        location = random.choice(PLACES)
        url = "https://pixabay.com/api/videos/"
        
        # Explicitly search for vertical/portrait video clips
        params = {
            "key": PIXABAY_KEY,
            "q": f"{location} vertical sunny beach",
            "video_type": "film",
            "per_page": 50
        }
        
        res = requests.get(url, params=params).json()
        hits = res.get("hits", [])
        
        # Strict validation against metadata tags and dimensions
        valid_vertical_hits = []
        for h in hits:
            tags = (h.get("tags") or "").lower()
            v_data = h.get("videos", {})
            
            # Check medium and small dimensions
            med_w = v_data.get("medium", {}).get("width", 0)
            med_h = v_data.get("medium", {}).get("height", 0)
            
            # Identify vertical videos via height > width OR vertical keywords in tags
            if med_h > med_w or any(k in tags for k in ["vertical", "portrait", "mobile"]):
                valid_vertical_hits.append(h)
        
        if valid_vertical_hits:
            chosen = random.choice(valid_vertical_hits)
            v_data = chosen["videos"]
            
            # Select stream URL prioritizing highest quality stream
            for size in ["large", "medium", "small"]:
                stream = v_data.get(size, {})
                if stream.get("url"):
                    return stream["url"], location

    # Fallback to broader vertical Mediterranean search if specific location yields no vertical tags
    fallback_url = "https://pixabay.com/api/videos/"
    fallback_params = {
        "key": PIXABAY_KEY,
        "q": "Mediterranean vertical sunny sea",
        "video_type": "film",
        "per_page": 50
    }
    f_res = requests.get(fallback_url, params=fallback_params).json()
    f_hits = f_res.get("hits", [])
    if f_hits:
        chosen = random.choice(f_hits)
        v_data = chosen["videos"]
        stream = v_data.get("medium", {}) or v_data.get("small", {})
        return stream["url"], "Mediterranean Sea"

    raise Exception("Could not find a strictly vertical video on Pixabay.")

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
                raise Exception("Gemini API failed after 4 attempts due to server traffic.") from e

def wait_until_ready(container_id):
    print("Waiting for Meta servers to process the vertical video container...")
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
    print("Fetching strictly vertical Mediterranean video from Pixabay...")
    video_url, location = get_pixabay_video()
    print(f"Selected Video Stream URL: {video_url}")
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    reel_id = post_reel(video_url, caption)
    print(f"Successfully published Reel ID: {reel_id}")

if __name__ == "__main__":
    run()
