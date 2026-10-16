import os
import time
import random
import requests
import subprocess
import json
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
COVERR_KEY = os.environ.get("COVERR_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GRAPH = "https://graph.facebook.com/v26.0"

PLACES = [
    "Amalfi coast", "Positano", "Capri", "Cinque Terre", "Sardinia", 
    "Santorini", "Mykonos", "Crete", "Bodrum", "Antalya", "Fethiye", 
    "French Riviera", "Corsica", "Monaco", "Mallorca", "Ibiza", 
    "Dubrovnik", "Malta", "Cyprus"
]

def verify_stream_dimensions_ffprobe(video_url):
    """Probes the raw video stream header via HTTP to return true pixel dimensions."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:stream_tags=rotate",
        "-of", "json",
        video_url
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return None, None
        
        width = int(streams[0].get("width", 0))
        height = int(streams[0].get("height", 0))
        
        # Adjust for metadata rotation tags (e.g. mobile 90/270 degree rot)
        tags = streams[0].get("tags", {})
        rotation = int(tags.get("rotate", 0)) if "rotate" in tags else 0
        if abs(rotation) in (90, 270):
            width, height = height, width
            
        return width, height
    except Exception as e:
        print(f"ffprobe inspection failed: {e}")
        return None, None

def get_bulletproof_vertical_video():
    candidates = []
    
    # Collect candidate links from Pexels API
    if PEXELS_KEY:
        for _ in range(3):
            loc = random.choice(PLACES)
            url = f"https://api.pexels.com/videos/search?query={loc}&orientation=portrait&per_page=15"
            res = requests.get(url, headers={"Authorization": PEXELS_KEY})
            if res.status_code == 200:
                for v in res.json().get("videos", []):
                    for f in v.get("video_files", []):
                        if f.get("file_type") == "video/mp4" and f.get("link"):
                            candidates.append((f["link"], loc))

    # Collect candidate links from Coverr API
    if COVERR_KEY:
        for _ in range(3):
            loc = random.choice(PLACES)
            url = f"https://api.coverr.co/videos?query={loc.replace(' ', '+')}&aspect_ratio=9:16&urls=true"
            res = requests.get(url, headers={"Authorization": f"Bearer {COVERR_KEY}"})
            if res.status_code == 200:
                for hit in res.json().get("hits", []):
                    urls = hit.get("urls", {})
I completely understand your frustration. Stock video APIs are notoriously unreliable because contributors upload horizontal (16:9) drone footage inside vertical containers, or mislabel aspect ratio tags in the API metadata. Relying on API tags alone will always risk occasional letterboxing.

The **bulletproof solution** is to handle video validation and formatting inside the GitHub Actions runner itself using **FFmpeg**:

1. **Physical Stream Inspection**: The runner downloads the video and uses `ffprobe` to inspect the actual video stream dimensions, completely ignoring whatever the API claims.
2. **Auto-Cropping Engine**: If the video is horizontal or letterboxed, FFmpeg automatically center-crops and rescales it to an exact full-screen **$1080 \times 1920$ (9:16)** format.
3. **Guaranteed 9:16 Host**: Processed files are hosted with a direct public link before sending them to Meta, ensuring Meta **never** receives a horizontal video again.

---

### Step 1: Update `.github/workflows/reels.yml`
This adds `ffmpeg` to your GitHub runner so it can physically inspect and process video files.

Run this command in your Mac terminal:

```bash
cd ~/travel-mediterraneo-bot

cat << 'EOF' > .github/workflows/reels.yml
name: Post Mediterranean Reel

on:
  schedule:
    - cron: '0 16 * * *'
  workflow_dispatch:

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
          
      - name: Install FFmpeg
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg
          
      - name: Install dependencies
        run: pip install requests google-genai
        
      - name: Run Reels Bot
        env:
          INSTAGRAM_ACCESS_TOKEN: ${{ secrets.INSTAGRAM_ACCESS_TOKEN }}
          INSTAGRAM_ACCOUNT_ID: ${{ secrets.INSTAGRAM_ACCOUNT_ID }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          PEXELS_API_KEY: ${{ secrets.PEXELS_API_KEY }}
          PIXABAY_API_KEY: ${{ secrets.PIXABAY_API_KEY }}
          COVERR_API_KEY: ${{ secrets.COVERR_API_KEY }}
        run: python reels.py
