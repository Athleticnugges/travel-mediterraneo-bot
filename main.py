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
        base_location = random.choice(SEARCH_TERMS)
        search_query = f"{base_location} bright sunny daylight".replace(' ', '+')
        
        url = f"https://api.unsplash.com/photos/random?query={search_query}&orientation=squarish&client_id={UNSPLASH_KEY}"
        res = requests.get(url).json()
        
        if 'errors' not in res and 'urls' in res:
            image_url = res['urls']['regular']
            location = res.get('location', {}).get('name') or base_location
            return image_url, location

    fallback_url = f"https://api.unsplash.com/photos/random?query=Mediterranean+bright+sunny+daylight&orientation=squarish&client_id={UNSPLASH_KEY}"
    res = requests.get(fallback_url).json()
    return res['urls']['regular'], "Mediterranean Sea"

def generate_caption(location):
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Write a casual Instagram caption for the Mediterranean location: {location}.

    CRITICAL INSTRUCTIONS:
    - MAXIMUM 2 SENTENCES. You must write exactly 1 or 2 sentences.
    - NO HYPHENS. You are strictly forbidden from using the "-" character anywhere.
    - NO HASHTAGS.
    - DO NOT describe the visual appearance of the photo (no lighting, weather, or colors).
    - Share a brief piece of history or local mythology about the destination. Make it sound highly natural and human, like a friend casually sharing a cool fact they just learned.
    - Include the flag emoji of the country it belongs to.
    - If you write a second sentence, make it a natural, conversational question for the audience.
    - DO NOT use robotic AI words (e.g., discover, unveil, nestled, embark, dive into, imagine, a testament to).
    """
    response = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=prompt,
    )
    
    # Strip out any hyphens or dashes as a hard safeguard, and fix any double spaces it creates
    clean_caption = response.text.strip().replace("-", " ").replace("  ", " ")
    return clean_caption

def post_to_instagram(image_url, caption):
    container_url = f"https://graph.facebook.com/v26.0/{ACCOUNT_ID}/media"
    payload = {
        'image_url': image_url,
        'caption': caption,
        'access_token': ACCESS_TOKEN
    }
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
    post_to_instagram(image_url, caption)
    print("Successfully published! Hands-off mode complete.")

if __name__ == "__main__":
    run()
