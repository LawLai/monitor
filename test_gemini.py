"""Quick test: Gemini API + Google Search grounding"""
import os
from google import genai

key = os.environ.get("GEMINI_API_KEY", "")
if not key:
    print("ERROR: GEMINI_API_KEY not set")
    print("Run:  set GEMINI_API_KEY=AIzaSy...")
    exit(1)

print(f"API key: {key[:8]}...")
print("Searching for US-Iran war news via Gemini + Google Search...")
print()

client = genai.Client(api_key=key)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Search for the latest US-Iran war news from the last 24 hours. "
             "Cover military developments, diplomatic moves, and oil/economic impact. "
             "Give a concise summary of the top 5-8 developments.",
    config=genai.types.GenerateContentConfig(
        tools=[genai.types.Tool(google_search=genai.types.GoogleSearch())],
    ),
)

print("=== GEMINI SEARCH RESULTS ===")
print(response.text[:2000])
print()

if response.usage_metadata:
    inp = response.usage_metadata.prompt_token_count or 0
    out = response.usage_metadata.candidates_token_count or 0
    print(f"Tokens: {inp:,} input | {out:,} output")
    cost = inp / 1_000_000 * 0.10 + out / 1_000_000 * 0.40
    print(f"Est. cost: ${cost:.6f}")

print()
print("SUCCESS - Gemini search is working!")
