import os
import time
import random
import requests
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
UNSPLASH_KEY = os.environ["UNSPLASH_ACCESS_KEY"]

SEARCH_TERMS = [
    "Mediterranean coast", "Amalfi coast", "Bodrum Turkey", "Santorini Greece",
    "French Riviera", "Cinque Terre", "Mallorca coast", "Corsica",
    "Sardinia beach", "Dalmatian coast Croatia", "Cyprus beach", "Ibiza coast",
    "Positano", "Monaco coast", "Malta coast", "Antalya coast", "Fethiye", 
    "Mykonos", "Capri Italy", "Costa Brava", "Bodrum Harbour"
]

def get_unsplash_photo():
    for _ in range(3):
        location = random.choice(SEARCH_TERMS)
        # Stacking extreme brightness keywords to force the happiest, sun-filled photos
        search_query = f"{location} bright sunshine happy sunny vibrant clear blue sky landscape empty".replace(' ', '+')
        
        url = f"https://api.unsplash.com/search/photos?query={search_query}&orientation=squarish&per_page=30&client_id={UNSPLASH_KEY}"
        res = requests.get(url).json()
        
        if 'results' in res and len(res['results']) > 0:
            chosen_photo = random.choice(res['results'])
            image_url = chosen_photo['urls']['regular']
            return image_url, location

    fallback_url = f"https://api.unsplash.com/search/photos?query=Mediterranean+bright+sunshine+happy+sunny+vibrant+clear+sky+landscape+empty&orientation=squarish&per_page=30&client_id={UNSPLASH_KEY}"
    res = requests.get(fallback_url).json()
    chosen_photo = random.choice(res['results'])
    return chosen_photo['urls']['regular'], "Mediterranean Sea"

def generate_caption(location):
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Generate a minimalist Instagram caption for the Mediterranean location: {location}.

    CRITICAL INSTRUCTIONS:
    Output EXACTLY this format and nothing else. 
    1. Line 1: [Specific Island/City Name], [Country] ☀️ [Country Flag Emoji]
    2. Line 2: Exactly ONE short, interesting sentence sharing a random fact about the location.
    3. Line 3: A blank line.
    4. Line 4: Exactly 3 to 4 hashtags.
    DO NOT USE HYPHENS ("-") OR DASHES ANYWHERE.

    Example Output:
    Syros island, Greece ☀️ 🇬🇷
    This hidden gem was once the maritime center of Greece before Athens took over.

    #syros #syrosisland #greece
    """
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt,
            )
            # Hyphen scrubber remains active to protect the clean formatting
            clean_caption = response.text.strip().replace("-", " ").replace("  ", " ")
            return clean_caption
        except Exception as e:
            print(f"Gemini API error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                print("Waiting 30 seconds before retrying...")
                time.sleep(30)
            else:
                raise Exception("Gemini API failed after 3 attempts.") from e

def get_facebook_location_id(location_query):
    search_url = "https://graph.facebook.com/v26.0/pages/search"
    params = {
        'q': location_query,
        'fields': 'id,name,location',
        'access_token': ACCESS_TOKEN
    }
    try:
        res = requests.get(search_url, params=params).json()
        for page in res.get('data', []):
            if 'location' in page:
                return page['id']
    except Exception as e:
        print(f"Location search warning: {e}")
    return None

def post_to_instagram(image_url, caption, location):
    location_id = get_facebook_location_id(location)
    
    container_url = f"https://graph.facebook.com/v26.0/{ACCOUNT_ID}/media"
    payload = {
        'image_url': image_url,
        'caption': caption,
        'access_token': ACCESS_TOKEN
    }
    
    if location_id:
        payload['location_id'] = location_id
        print(f"Attaching verified geotag ID: {location_id}")

    res = requests.post(container_url, data=payload).json()
    creation_id = res.get('id')
    if not creation_id:
        raise Exception(f"Failed to create media container: {res}")

    time.sleep(15)

    publish_url = f"https://graph.facebook.com/v26.0/{ACCOUNT_ID}/media_publish"
    publish_payload = {
        'creation_id': creation_id,
        'access_token': ACCESS_TOKEN
    }
    return requests.post(publish_url, data=publish_payload).json()

def run():
    print("Fetching top-rated sunny Mediterranean photo...")
    image_url, location = get_unsplash_photo()
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    print("Publishing to Instagram...")
    post_to_instagram(image_url, caption, location)
    print("Successfully published! Hands-off mode complete.")

if __name__ == "__main__":
    run()
