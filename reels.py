import os
import time
import random
import requests
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "536453000001000000000000000000000000") # Fallback or set PEXELS_API_KEY in secrets
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GRAPH = "https://graph.facebook.com/v26.0"

PLACES = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Sardinia", 
    "Santorini", "Mykonos", "Crete", "Bodrum", "Antalya", "Fethiye", 
    "French Riviera", "Corsica", "Monaco", "Mallorca", "Ibiza", 
    "Dubrovnik", "Malta", "Cyprus"
]

def get_vertical_video():
    # Primary lookup using Pexels Video API enforcing strict portrait orientation
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY", "")}
    
    for attempt in range(5):
        location = random.choice(PLACES)
        url = f"https://api.pexels.com/videos/search?query={location}&orientation=portrait&per_page=15"
        res = requests.get(url, headers=headers)
        
        if res.status_code == 200:
            videos = res.json().get("videos", [])
            for video in videos:
                # Strictly filter for streams where height > width (true 9:16)
                if video.get("height", 0) > video.get("width", 0):
                    video_files = video.get("video_files", [])
                    # Pick highest resolution HD MP4 file
                    hd_files = [f for f in video_files if f.get("quality") == "hd" and f.get("file_type") == "video/mp4"]
                    if hd_files:
                        return hd_files[0]["link"], location
                    elif video_files:
                        return video_files[0]["link"], location

    # Secondary fallback using Pixabay API with strict dimensional filtering
    pixabay_key = os.environ.get("PIXABAY_API_KEY")
    if pixabay_key:
        pb_url = f"https://pixabay.com/api/videos/?key={pixabay_key}&q=mediterranean+sea&video_type=film"
        pb_res = requests.get(pb_url).json()
        for hit in pb_res.get("hits", []):
            videos_dict = hit.get("videos", {})
            large_v = videos_dict.get("large", {})
            if large_v.get("height", 0) > large_v.get("width", 0):
                return large_v.get("url"), "Mediterranean Coast"

    raise Exception("Could not find a true 9:16 vertical video stream.")

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
    print("Fetching strictly vertical (9:16) video stream...")
    video_url, location = get_vertical_video()
    print(f"Selected 9:16 Video Stream: {video_url}")
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    reel_id = post_reel(video_url, caption)
    print(f"Successfully published Reel ID: {reel_id}")

if __name__ == "__main__":
    run()
