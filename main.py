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
        query = random.choice(SEARCH_TERMS)
        url = f"https://api.unsplash.com/photos/random?query={query}&orientation=squarish&client_id={UNSPLASH_KEY}"
        res = requests.get(url).json()
        
        if 'errors' not in res and 'urls' in res:
            image_url = res['urls']['regular']
            photographer = res['user']['username']
            location = res.get('location', {}).get('name') or query
            return image_url, photographer, location

    fallback_url = f"https://api.unsplash.com/photos/random?query=Mediterranean&orientation=squarish&client_id={UNSPLASH_KEY}"
    res = requests.get(fallback_url).json()
    return res['urls']['regular'], res['user']['username'], "Mediterranean Sea"

def generate_caption(location, photographer):
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Write a short, casual Instagram caption for a beautiful photo of {location}.
    Write exactly 3 to 4 sentences describing the scenery, the water, or the atmosphere. 
    Make it sound completely natural and human, like a traveler sharing a personal memory. 
    Do NOT use robotic AI buzzwords like 'discover', 'unveil', 'nestled', or 'embark'. 
    End with: 📸 Photo by @{photographer} on Unsplash
    Include exactly 4 relevant hashtags.
    """
    response = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=prompt,
    )
    return response.text.strip()

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
    image_url, photographer, location = get_unsplash_photo()
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location, photographer)
    
    print("Publishing to Instagram...")
    post_to_instagram(image_url, caption)
    print("Successfully published! Hands-off mode complete.")

if __name__ == "__main__":
    run()
