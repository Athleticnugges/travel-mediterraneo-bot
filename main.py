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
        # We now lock onto this base_location to ensure the photo, caption, and geotag match perfectly
        location = random.choice(SEARCH_TERMS)
        search_query = f"{location} bright sunny daylight".replace(' ', '+')
        
        url = f"https://api.unsplash.com/photos/random?query={search_query}&orientation=squarish&client_id={UNSPLASH_KEY}"
        res = requests.get(url).json()
        
        if 'errors' not in res and 'urls' in res:
            image_url = res['urls']['regular']
            return image_url, location

    fallback_url = f"https://api.unsplash.com/photos/random?query=Mediterranean+bright+sunny+daylight&orientation=squarish&client_id={UNSPLASH_KEY}"
    res = requests.get(fallback_url).json()
    return res['urls']['regular'], "Mediterranean Sea"

def generate_caption(location):
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Write a casual Instagram caption for the Mediterranean location: {location}.

    CRITICAL INSTRUCTIONS:
    - STRICTLY THIRD PERSON: NEVER use first-person pronouns like "I", "me", "my", or "we".
    - MAXIMUM 2 SENTENCES. You must write exactly 1 or 2 sentences.
    - NO HYPHENS. You are strictly forbidden from using the "-" character anywhere.
    - NO HASHTAGS. Do not generate hashtags.
    - DO NOT describe the visual appearance of the photo (no lighting, weather, or colors).
    - Share a brief piece of history or local mythology about the destination. Make it sound conversational, but stick to objective facts.
    - Include the flag emoji of the country it belongs to.
    - If you write a second sentence, make it a natural, conversational question for the audience.
    - DO NOT use robotic AI words (e.g., discover, unveil, nestled, embark, dive into, imagine, a testament to).
    """
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt,
            )
            
            clean_caption = response.text.strip()
            clean_caption = clean_caption.replace("-", " ")
            clean_caption = clean_caption.replace("#", "")
            clean_caption = clean_caption.replace("*", "")
            clean_caption = clean_caption.replace("  ", " ")
            
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
        # Instagram rejects the geotag if the Facebook page doesn't have a physical 'location' object attached to it
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
    print("Fetching random Mediterranean photo...")
    image_url, location = get_unsplash_photo()
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    print("Publishing to Instagram...")
    post_to_instagram(image_url, caption, location)
    print("Successfully published! Hands-off mode complete.")

if __name__ == "__main__":
    run()
