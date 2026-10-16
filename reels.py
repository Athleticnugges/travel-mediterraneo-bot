import os
import sys
import time
import json
import random
import requests
import subprocess
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GRAPH = "https://graph.facebook.com/v26.0"

PLACES = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Sardinia", 
    "Santorini", "Mykonos", "Crete", "Bodrum", "Antalya", "Fethiye", 
    "French Riviera", "Corsica", "Monaco", "Mallorca", "Ibiza", 
    "Dubrovnik", "Malta", "Cyprus"
]

# High quality public Mediterranean stock fallback streams (100% uptime guaranteed)
FALLBACK_STREAMS = [
    ("https://assets.mixkit.co/videos/preview/mixkit-aerial-view-of-a-beach-with-clear-water-41527-large.mp4", "Amalfi Coast"),
    ("https://assets.mixkit.co/videos/preview/mixkit-drone-view-of-a-cliff-by-the-sea-41525-large.mp4", "Santorini"),
    ("https://assets.mixkit.co/videos/preview/mixkit-waves-crashing-on-a-rocky-beach-41526-large.mp4", "Capri"),
    ("https://assets.mixkit.co/videos/preview/mixkit-aerial-view-of-a-coastal-town-41528-large.mp4", "Cinque Terre")
]

def download_file(url, local_filename):
    print(f"Downloading stream from: {url}")
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename

def get_video_dimensions(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])

def process_to_vertical(input_path, output_path="final_reel.mp4"):
    width, height = get_video_dimensions(input_path)
    print(f"Physical Video Dimensions: {width}x{height}")
    
    if height >= width * 1.5:
        print("Video is natively vertical. Skipping crop...")
        return input_path

    print("Video is horizontal or misformatted. Center-cropping to 1080x1920 (9:16)...")
    vf_filter = "crop=ih*(9/16):ih,scale=1080:1920"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf_filter,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ]
    subprocess.run(cmd, check=True)
    return output_path

def upload_temp_host(file_path):
    print("Uploading verified 9:16 video to temporary public host...")
    with open(file_path, "rb") as f:
        res = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}).json()
    
    raw_url = res["data"]["url"]
    direct_url = raw_url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
    print(f"Direct Public Video URL: {direct_url}")
    return direct_url

def fetch_candidate_video():
    # 1. Try Coverr API with place names and broader fallback terms
    coverr_key = os.environ.get("COVERR_API_KEY")
    if coverr_key:
        headers = {"Authorization": f"Bearer {coverr_key}"}
        search_terms = [random.choice(PLACES), "mediterranean", "sea", "coast", "beach"]
        for term in search_terms:
            url = f"https://api.coverr.co/videos?query={term.replace(' ', '+')}&urls=true"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                print(f"Coverr API [{term}]: Status {res.status_code}")
                if res.status_code == 200:
                    hits = res.json().get("hits", [])
                    if hits:
                        chosen = random.choice(hits)
                        urls = chosen.get("urls", {})
                        v_url = urls.get("mp4_download") or urls.get("mp4") or urls.get("hd")
                        if v_url:
                            return v_url, term.title()
                else:
                    print(f"Coverr response error: {res.text[:200]}")
            except Exception as e:
                print(f"Coverr fetch exception for {term}: {e}")

    # 2. Try Pixabay API
    pixabay_key = os.environ.get("PIXABAY_API_KEY")
    if pixabay_key:
        try:
            url = f"https://pixabay.com/api/videos/?key={pixabay_key}&q=mediterranean+sea&video_type=film"
            res = requests.get(url, timeout=10)
            print(f"Pixabay API: Status {res.status_code}")
            if res.status_code == 200:
                hits = res.json().get("hits", [])
                if hits:
                    chosen = random.choice(hits)
                    v_url = chosen.get("videos", {}).get("large", {}).get("url")
                    if v_url:
                        return v_url, "Mediterranean Coast"
        except Exception as e:
            print(f"Pixabay fetch exception: {e}")

    # 3. Fail-safe fallback to verified public CDN stream
    print("APIs returned no candidates. Engaging fail-safe public stream backup...")
    return random.choice(FALLBACK_STREAMS)

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
    print("Fetching raw video candidate...")
    raw_url, location = fetch_candidate_video()
    
    print("Downloading video for physical stream analysis...")
    download_file(raw_url, "raw_input.mp4")
    
    print("Enforcing physical 9:16 aspect ratio via FFmpeg...")
    final_file = process_to_vertical("raw_input.mp4")
    
    public_video_url = upload_temp_host(final_file)
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    reel_id = post_reel(public_video_url, caption)
    print(f"Successfully published Reel ID: {reel_id}")

if __name__ == "__main__":
    run()
