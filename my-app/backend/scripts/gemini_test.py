import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

for model in ("gemini-2.5-flash", "gemini-3.5-flash"):
    try:
        r = client.models.generate_content(model=model, contents="Reply with the single word: ok")
        print(model, "->", r.text.strip())
    except Exception as e:
        print(model, "FAILED:", e)