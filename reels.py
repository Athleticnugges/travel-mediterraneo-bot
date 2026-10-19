import os
import time
import random
import requests
import subprocess
import json
from google.genai import Client, errors

# --- 1. CONFIGURATION & CREDENTIALS ---
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
COVERR_API_KEY = os.environ.get("COVERR_API_KEY")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

HISTORY_FILE = "posted_reels.json"

MEDITERRANEAN_LOCATIONS = [
    "Amalfi Coast Italy", "Santorini Greece architecture",
    "Cinque Terre coastal", "Mykonos aerial", "Dubrovnik Croatia walls",
    "Corsica France beach", "Sardinia Italy coast", "Capri Italy boat",
    "Positano Italy", "Mallorca Spain coast", "Ibiza Spain Mediterranean",
    "Malta Valetta coast", "French Riviera aerial", "Zakynthos Greece water"
]

# --- 2. MEMORY: LOAD & SAVE HISTORY ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)

# --- 3. FETCH UNIQUE STOCK VIDEO ---
def get_mediterranean_video_url(location, history):
    print(f"🔎 Searching stock APIs for: {location}")
    
    if PEXELS_API_KEY:
        try:
            url = f"https://api.pexels.com/videos/search?query={location}&orientation=portrait&per_page=15"
            res = requests.get(url, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
            res.raise_for_status()
            data = res.json()
            videos = data.get('videos', [])
            random.shuffle(videos)
            for video in videos:
                hd_files = [f for f in video.get('video_files', []) if f.get('height', 0) > f.get('width', 0)]
                link = hd_files[0]['link'] if hd_files else video['video_files'][0]['link']
                if link not in history:
                    print("✅ Found unique video on Pexels")
                    return link
        except Exception as e:
            print(f"⚠️ Pexels search failed: {e}")

    if PIXABAY_API_KEY:
        try:
            url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={requests.utils.quote(location)}&video_type=film"
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            data = res.json()
            hits = data.get('hits', [])
            random.shuffle(hits)
            for video in hits:
                urls = video.get('videos', {})
                link = urls.get('large', {}).get('url') or urls.get('medium', {}).get('url')
                if link and link not in history:
                    print("✅ Found unique video on Pixabay")
                    return link
        except Exception as e:
            print(f"⚠️ Pixabay search failed: {e}")

    if COVERR_API_KEY:
        try:
            url = f"https://api.coverr.co/videos?query={requests.utils.quote(location)}"
            res = requests.get(url, headers={"Authorization": f"Bearer {COVERR_API_KEY}"}, timeout=15)
            res.raise_for_status()
            data = res.json()
            hits = data.get('hits', [])
            random.shuffle(hits)
            for video in hits:
                link = video.get('urls', {}).get('mp4')
                if link and link not in history:
                    print("✅ Found unique video on Coverr")
                    return link
        except Exception as e:
            print(f"⚠️ Coverr search failed: {e}")

    return None

# --- 4. DOWNLOAD & PROCESS VIDEO (CLEAN 9:16 CROP + SILENT AUDIO) ---
def process_video(video_url):
    raw_path = "raw_input.mp4"
    final_path = "final_reel.mp4"
    
    print("📥 Downloading raw video file...")
    with requests.get(video_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(raw_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
    print("🎬 Processing video (9:16 clean crop, silent audio)...")
    
    vf_string = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    
    cmd = [
        "ffmpeg", "-y", "-i", raw_path,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264",
        "-vf", vf_string,
        "-c:a", "aac", 
        "-shortest",
        "-t", "15",
        "-movflags", "+faststart",
        final_path
    ]
    
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✅ Video processed successfully.")
    return final_path

# --- 5. GENERATE CAPTION (WITH FALLBACK) ---
def generate_caption(location):
    short_loc = " ".join(location.split(" ")[:2])
    fallback_captions = [
        f"Dreaming of the Mediterranean sun in {short_loc}. 🌊☀️ #travel #{short_loc.replace(' ', '')} #mediterranean",
        f"Escaping to {short_loc}. The perfect getaway. 🌴✈️ #{short_loc.replace(' ', '')} #travelgram #wanderlust",
        f"A perfect day in {short_loc}. You need to add this to your bucket list! 📍✨ #travelguide #mediterraneanlife",
        f"Taking in the beauty of {short_loc}. Can't wait to go back. 💙🇪🇺 #europeantravel #mediterranean"
    ]

    if not GEMINI_API_KEY:
        print("⚠️ No Gemini API key found. Using fallback caption.")
        return random.choice(fallback_captions)

    try:
        print(f"✍️ Attempting to generate caption via Gemini...")
        client = Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=f"Write a short, engaging Instagram caption for a travel reel about {short_loc}. Include 3 relevant hashtags."
        )
        return response.text.strip()
    except errors.ClientError as e:
        print(f"⚠️ Gemini API rate limit/error. Using fallback caption.")
        return random.choice(fallback_captions)
    except Exception as e:
        print(f"⚠️ Unexpected Gemini error. Using fallback caption.")
        return random.choice(fallback_captions)

# --- 6. DIRECT INSTAGRAM UPLOAD ---
def post_reel_resumable(video_path, caption):
    print("🚀 Initiating direct upload to Instagram...")
    graph = "https://graph.facebook.com/v26.0"
    
    res = requests.post(f"{graph}/{INSTAGRAM_ACCOUNT_ID}/media", data={
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "share_to_feed": "true",
        "access_token": INSTAGRAM_ACCESS_TOKEN,
    }, timeout=60).json()
    
    container_id = res.get("id")
    if not container_id:
        raise Exception(f"❌ Container creation failed: {res}")
    
    upload_url = res.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v26.0/{container_id}"

    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        up = requests.post(upload_url, headers={
            "Authorization": f"OAuth {INSTAGRAM_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(size),
        }, data=f, timeout=300)
    
    if up.status_code != 200:
        raise Exception(f"❌ Upload failed: {up.status_code} {up.text[:300]}")

    print("⏳ Waiting for Instagram to process the video...")
    for _ in range(60):
        st = requests.get(f"{graph}/{container_id}", params={
            "fields": "status_code,status", 
            "access_token": INSTAGRAM_ACCESS_TOKEN
        }, timeout=30).json()
        
        status = st.get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise Exception(f"❌ Reel processing failed on Instagram's end: {st}")
        time.sleep(5)
    else:
        raise Exception("❌ Reel processing timed out")

    print("📝 Publishing Reel...")
    out = requests.post(f"{graph}/{INSTAGRAM_ACCOUNT_ID}/media_publish", data={
        "creation_id": container_id, 
        "access_token": INSTAGRAM_ACCESS_TOKEN
    }, timeout=60).json()
    
    if "id" not in out:
        raise Exception(f"❌ Publish failed: {out}")
    print(f"🎉 Reel published successfully! IG Media ID: {out['id']}")
    return out["id"]

# --- 7. MAIN EXECUTION WITH RETRY LOOP ---
def run():
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        raise Exception("❌ Missing INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_ACCOUNT_ID.")

    history = load_history()
    video_url = None
    target_location = None
    
    print("🔄 Initiating robust location search...")
    for attempt in range(5):
        target_location = random.choice(MEDITERRANEAN_LOCATIONS)
        video_url = get_mediterranean_video_url(target_location, history)
        if video_url:
            break
        print(f"⚠️ Attempt {attempt + 1}/5 failed to find unique video. Retrying with new location...")

    if not video_url:
        raise Exception("❌ Failed to find a unique, unposted video after 5 attempts.")

    final_video_path = process_video(video_url)
    caption = generate_caption(target_location)
    
    post_reel_resumable(final_video_path, caption)
    
    history.append(video_url)
    save_history(history)

if __name__ == "__main__":
    run()
