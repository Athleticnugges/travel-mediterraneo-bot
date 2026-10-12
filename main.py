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
        # Combine location with our vibe keywords and format for the URL
        search_query = f"{base_location} summer sunny vibrant".replace(' ', '+')
        
        url = f"https://api.unsplash.com/photos/random?query={search_query}&orientation=squarish&client_id={UNSPLASH_KEY}"
        res = requests.get(url).json()
        
        if 'errors' not in res and 'urls' in res:
            image_url = res['urls']['regular']
            # Provide the clean base_location to the AI so it doesn't get confused by the extra keywords
            location = res.get('location', {}).get('name') or base_location
            return image_url, location

    # Ultimate fallback with the same sunny constraints
    fallback_url = f"https://api.unsplash.com/photos/random?query=Mediterranean+summer+sunny+vibrant&orientation=squarish&client_id={UNSPLASH_KEY}"
    res = requests.get(fallback_url).json()
    return res['urls']['regular'], "Mediterranean Sea"

def generate_caption(location):
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Write an engaging Instagram caption for the Mediterranean location: {location}.

    CRITICAL INSTRUCTIONS:
    - DO NOT describe the visual appearance of the location. You must avoid mentioning the time of day, lighting, weather, colors, flora, or specific scenery (e.g., do not mention bright sun, blue water, or specific flowers).
    - Focus entirely on the history, local mythology, cultural significance, or the broader essence of the destination. Be sure to include the flag emoji of the country it belongs to.
    - Write in a captivating, sophisticated tone suitable for a travel page.
    - Keep the caption between 3 to 4 sentences.
    - End with 4-5 relevant hashtags.
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
    image_url, location = get_unsplash_photo()
    
    print(f"Generating caption for {location}...")
    caption = generate_caption(location)
    
    print("Publishing to Instagram...")
    post_to_instagram(image_url, caption)
    print("Successfully published! Hands-off mode complete.")

if __name__ == "__main__":
    run()
