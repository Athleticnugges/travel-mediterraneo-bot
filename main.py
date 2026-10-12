import os
import json
import time
import requests
from google import genai

ACCESS_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
ACCOUNT_ID = os.environ["INSTAGRAM_ACCOUNT_ID"]
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

def generate_caption(location, credit):
    if not GEMINI_KEY:
        return f"📍 {location}\n\nPhoto by: {credit}\n\n#travelmediterraneo #mediterraneansea"
    
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Write a detailed, high-engagement Instagram caption for: {location}.
    Include geography details, cultural history, 3 must-visit spots, local dish recommendation, 
    photo credit to {credit}, and 15 relevant hashtags (#travelmediterraneo #mediterraneansea #coastalvibes).
    """
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    return response.text

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
    with open('locations.json', 'r') as f:
        locations = json.load(f)

    for item in locations:
        if not item.get('published', False):
            print(f"Publishing: {item['location']}")
            caption = generate_caption(item['location'], item['credit'])
            post_to_instagram(item['image_url'], caption)
            item['published'] = True
            break
    else:
        print("No pending posts found in queue.")
        return

    with open('locations.json', 'w') as f:
        json.dump(locations, f, indent=2)

if __name__ == "__main__":
    run()
