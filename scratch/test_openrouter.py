import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Initialize the client pointing to OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

def get_chat_completion():
    try:
        response = client.chat.completions.create(
            # Specify the provider and model
            model="anthropic/claude-3-haiku", # e.g., google/gemini-1.5-pro, meta-llama/llama-3-70b-instruct
            messages=[
                {"role": "system", "content": "You are a highly skilled AI architect."},
                {"role": "user", "content": "Explain the benefits of multi-agent architectures."}
            ],
            # Optional OpenRouter headers for analytics/tracking
            extra_headers={
                "HTTP-Referer": "https://github.com/google-deepmind/antigravity", # Site URL
                "X-Title": "Antigravity Test", # Site Title
            }
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    print("Connecting to OpenRouter...")
    result = get_chat_completion()
    print("\nResult from Claude-3-Sonnet via OpenRouter:\n")
    print(result)
