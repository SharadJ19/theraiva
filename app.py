from flask import Flask, render_template, request, jsonify, session
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone
from google import genai  # Gemini SDK

load_dotenv()
app = Flask(__name__)
app.secret_key = "supersecretkey"

# MongoDB setup
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME")
client_db = MongoClient(MONGODB_URI)
db = client_db[DB_NAME]
users_collection = db["users"]

# Gemini client
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_MESSAGE = """
You are a friendly, compassionate, and professional AI assistant named Theraiva. 
Your goal is to help young adults (ages 18–24) who are experiencing stress, anxiety, or depression. 
Respond with empathy, warmth, and clarity, providing practical guidance and encouragement. 

- Write in a **conversational and human-friendly style**, as if speaking to a supportive friend or coach.  
- Use **Markdown formatting** for all responses, including headings, bold/italic text, lists, links, blockquotes, and code blocks if appropriate.  
- Provide **at least one actionable coping strategy or helpful tip** in every message.  
- Avoid repeating advice or sentences you’ve given earlier in the conversation.  
- If the user's name is known, **address them by name** naturally.  
- Keep messages concise, safe, and encouraging; do not provide medical diagnoses or instructions.  
- Respond only to the current message, maintaining context but avoiding answering previous messages again.  

Always prioritize **clarity, empathy, and helpfulness**, making the response feel thoughtful and supportive.
"""


SAFETY_KEYWORDS = ["suicide", "self-harm", "kill myself"]
HELPLINE = "If you are thinking about self-harm, please contact a trained professional or call your local helpline immediately."

# MongoDB helpers
def get_user(user_id):
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        user = {"user_id": user_id, "conversations": [], "created_at": datetime.now(timezone.utc)}
        users_collection.insert_one(user)
    return user

def save_message(user_id, role, content):
    users_collection.update_one(
        {"user_id": user_id},
        {"$push": {"conversations": {"role": role, "content": content, "timestamp": datetime.now(timezone.utc)}}}
    )

def get_recent_messages(user, limit=10):
    messages = user.get("conversations", [])[-limit:]
    for m in messages:
        if isinstance(m.get("timestamp"), datetime):
            m["timestamp"] = m["timestamp"].isoformat()
    return messages

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip()
    user_name = data.get("userName", "").strip()
    user_id = session.get("user_id")

    if not user_id:
        user_id = str(len(list(users_collection.find({}))) + 1)
        session["user_id"] = user_id

    user = get_user(user_id)

    if user_name and user.get("name") != user_name:
        users_collection.update_one({"user_id": user_id}, {"$set": {"name": user_name}})
        user["name"] = user_name

    # Safety check
    for keyword in SAFETY_KEYWORDS:
        if keyword in user_message.lower():
            return jsonify({"reply": HELPLINE})

    # Save user message
    save_message(user_id, "user", user_message)

    # Build prompt including current message
    recent_messages = get_recent_messages(user, limit=10)
    recent_messages.append({"role": "user", "content": user_message})

    prompt = SYSTEM_MESSAGE + "\n"
    if user.get("name"):
        prompt += f"The user's name is {user['name']}.\n"

    for msg in recent_messages:
        prompt += f"{msg['role']}: {msg['content']}\n"

    # Gemini API call
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        ai_message = response.text.strip()  # assume Markdown
        save_message(user_id, "assistant", ai_message)
        return jsonify({"reply": ai_message})
    except Exception as e:
        print(e)
        return jsonify({"reply": "Sorry, something went wrong with the AI."})

if __name__ == "__main__":
    app.run(debug=True,host='0.0.0.0')
