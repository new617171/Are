# app.py - Main application file
import requests
import json
import logging
import os
from datetime import datetime
from flask import Flask, request, jsonify
import threading
import time

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    def __init__(self):
        self.page_access_token = self.load_token()
        self.verify_token = os.getenv("VERIFY_TOKEN", "SECURE_VERIFY_TOKEN_2024")
        self.api_version = "v18.0"
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        
    def load_token(self):
        """Load page access token from environment variable (Render) or token.txt (local)"""
        # Try environment variable first (for Render)
        token = os.getenv("PAGE_ACCESS_TOKEN")
        if token:
            logger.info("[+] Token loaded from environment variable")
            return token
            
        # Try token.txt file (for local development)
        try:
            with open("token.txt", "r", encoding="utf-8") as file:
                token = file.read().strip()
                if token:
                    logger.info("[+] Token loaded from token.txt")
                    return token
        except FileNotFoundError:
            logger.warning("[-] token.txt file not found")
        except Exception as e:
            logger.error(f"[-] Error reading token.txt: {e}")
        
        logger.error("[-] No access token found! Set PAGE_ACCESS_TOKEN environment variable or create token.txt")
        return None

config = Config()

# Global state management
class BotState:
    def __init__(self):
        self.reply_index = 0
        self.user_states = {}
        self.lock = threading.Lock()
        self.last_reply_reload = 0
        self.replies_cache = []
        
    def load_replies(self, force_reload=False):
        """Load replies with caching and auto-reload"""
        current_time = time.time()
        
        if force_reload or (current_time - self.last_reply_reload) > 30:
            try:
                with open("reply.txt", "r", encoding="utf-8") as file:
                    self.replies_cache = [line.strip() for line in file if line.strip()]
                self.last_reply_reload = current_time
                logger.info(f"[+] Loaded {len(self.replies_cache)} replies")
            except FileNotFoundError:
                logger.warning("[-] reply.txt not found, creating default replies")
                self.create_default_replies()
            except Exception as e:
                logger.error(f"[-] Error loading replies: {e}")
                self.replies_cache = ["Thanks for messaging us! We'll get back to you soon. 😊"]
        
        return self.replies_cache
    
    def create_default_replies(self):
        """Create default reply.txt if it doesn't exist"""
        default_replies = [
            "Hello! Thanks for messaging us. We'll get back to you soon! 😊",
            "Thanks for reaching out! How can we help you today?",
            "We appreciate your message. Our team will respond shortly.",
            "Hello there! We're here to help. What can we do for you?",
            "Thanks for contacting us! We value your inquiry.",
            "Hi! We've received your message and will respond as soon as possible.",
            "Hello! Thanks for getting in touch. We're here to assist you.",
            "We appreciate you reaching out to us today! 🙌",
            "Thanks for your message! Our team is ready to help.",
            "Hello! We're glad you contacted us. How may we assist you?"
        ]
        
        try:
            with open("reply.txt", "w", encoding="utf-8") as file:
                file.write("\n".join(default_replies))
            self.replies_cache = default_replies
            logger.info("[+] Created default reply.txt with sample replies")
        except Exception as e:
            logger.error(f"[-] Could not create reply.txt: {e}")
            self.replies_cache = default_replies
    
    def get_next_reply(self, user_id=None):
        """Get next reply with user-specific tracking"""
        with self.lock:
            replies = self.load_replies()
            
            if not replies:
                return "Thanks for your message! 😊"
            
            if user_id:
                if user_id not in self.user_states:
                    self.user_states[user_id] = {"reply_index": 0, "last_active": time.time()}
                
                user_state = self.user_states[user_id]
                reply = replies[user_state["reply_index"] % len(replies)]
                user_state["reply_index"] += 1
                user_state["last_active"] = time.time()
            else:
                reply = replies[self.reply_index % len(replies)]
                self.reply_index += 1
            
            return reply
    
    def cleanup_inactive_users(self):
        """Clean up inactive users (older than 1 hour)"""
        current_time = time.time()
        inactive_threshold = 3600
        
        with self.lock:
            inactive_users = [
                user_id for user_id, state in self.user_states.items()
                if current_time - state["last_active"] > inactive_threshold
            ]
            
            for user_id in inactive_users:
                del self.user_states[user_id]
                
            if inactive_users:
                logger.info(f"[+] Cleaned up {len(inactive_users)} inactive users")

bot_state = BotState()

class MessengerAPI:
    """Handle Facebook Messenger API interactions"""
    
    @staticmethod
    def send_message(recipient_id, text, message_type="RESPONSE"):
        """Send message with error handling"""
        if not config.page_access_token:
            logger.error("[-] Access token missing")
            return False

        url = f"{config.base_url}/me/messages"
        params = {"access_token": config.page_access_token}
        headers = {"Content-Type": "application/json"}
        
        # Truncate message if too long (Facebook limit: 2000 chars)
        if len(text) > 2000:
            text = text[:1997] + "..."
        
        data = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
            "messaging_type": message_type
        }
        
        try:
            response = requests.post(
                url, 
                params=params, 
                headers=headers, 
                json=data, 
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"[+] Message sent to {recipient_id}: {text[:50]}...")
                return True
            else:
                try:
                    error_data = response.json()
                    logger.error(f"[-] API Error: {error_data}")
                except:
                    logger.error(f"[-] HTTP Error: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("[-] Request timeout")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"[-] Request error: {e}")
            return False
        except Exception as e:
            logger.error(f"[-] Unexpected error: {e}")
            return False
    
    @staticmethod
    def send_typing_indicator(recipient_id, action="typing_on"):
        """Send typing indicator for natural conversation feel"""
        if not config.page_access_token:
            return False

        url = f"{config.base_url}/me/messages"
        params = {"access_token": config.page_access_token}
        headers = {"Content-Type": "application/json"}
        
        data = {
            "recipient": {"id": recipient_id},
            "sender_action": action
        }
        
        try:
            response = requests.post(url, params=params, headers=headers, json=data, timeout=5)
            return response.status_code == 200
        except:
            return False

class MessageProcessor:
    """Process incoming messages and generate responses"""
    
    @staticmethod
    def process_message(sender_id, message_text, message_id):
        """Main message processing logic"""
        logger.info(f"[+] Processing message from {sender_id}: {message_text[:100]}...")
        
        # Send typing indicator
        MessengerAPI.send_typing_indicator(sender_id, "typing_on")
        
        # Small delay for natural response timing
        time.sleep(1)
        
        # Get sequential reply
        reply_text = bot_state.get_next_reply(sender_id)
        
        # Send the reply
        success = MessengerAPI.send_message(sender_id, reply_text)
        
        # Turn off typing indicator
        MessengerAPI.send_typing_indicator(sender_id, "typing_off")
        
        if success:
            logger.info(f"[+] Auto-reply sent to {sender_id}")
        else:
            logger.error(f"[-] Failed to send reply to {sender_id}")

# Main webhook endpoint
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Facebook webhook endpoint"""
    if request.method == "GET":
        return handle_webhook_verification()
    elif request.method == "POST":
        return handle_webhook_event()

def handle_webhook_verification():
    """Verify webhook with Facebook"""
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if token == config.verify_token:
        logger.info("[+] Webhook verified successfully ✅")
        return challenge
    else:
        logger.error("[-] Webhook verification failed ❌")
        return "Verification failed", 403

def handle_webhook_event():
    """Handle incoming Facebook webhook events"""
    try:
        data = request.json
        
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        # Process each entry in the webhook data
        for entry in data.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                process_messaging_event(messaging_event)
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"[-] Webhook processing error: {e}")
        return jsonify({"error": "Processing failed"}), 500

def process_messaging_event(messaging_event):
    """Process individual messaging events"""
    sender_id = messaging_event.get("sender", {}).get("id")
    
    if not sender_id:
        return
    
    # Handle different event types
    if "message" in messaging_event:
        handle_message_event(messaging_event, sender_id)
    elif "postback" in messaging_event:
        handle_postback_event(messaging_event, sender_id)

def handle_message_event(messaging_event, sender_id):
    """Handle incoming text messages"""
    message = messaging_event["message"]
    
    # Handle text messages
    if "text" in message:
        message_text = message["text"]
        message_id = message.get("mid", "")
        
        if message_text.strip():  # Only process non-empty messages
            # Process in background thread
            threading.Thread(
                target=MessageProcessor.process_message,
                args=(sender_id, message_text, message_id),
                daemon=True
            ).start()
    
    # Handle attachments (images, files, etc.)
    elif "attachments" in message:
        MessengerAPI.send_message(
            sender_id, 
            "Thanks for sharing! 📎 I can respond to text messages. How can I help you today?"
        )

def handle_postback_event(messaging_event, sender_id):
    """Handle button clicks and postbacks"""
    postback = messaging_event["postback"]
    payload = postback.get("payload", "")
    
    logger.info(f"[+] Postback from {sender_id}: {payload}")
    
    if payload == "GET_STARTED":
        MessengerAPI.send_message(
            sender_id,
            "🎉 Welcome! Thanks for getting started. How can we help you today?"
        )

# Management and monitoring endpoints
@app.route("/", methods=["GET"])
def home():
    """Health check and status endpoint"""
    return jsonify({
        "status": "🟢 RUNNING",
        "service": "Facebook Messenger Auto-Reply Bot",
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
        "replies_loaded": len(bot_state.load_replies()),
        "active_users": len(bot_state.user_states),
        "webhook_url": "/webhook",
        "management": {
            "reload_replies": "POST /reload_replies",
            "statistics": "GET /stats",
            "health": "GET /"
        }
    })

@app.route("/reload_replies", methods=["POST"])
def reload_replies():
    """Manually reload reply.txt"""
    try:
        old_count = len(bot_state.replies_cache)
        bot_state.load_replies(force_reload=True)
        new_count = len(bot_state.replies_cache)
        
        return jsonify({
            "status": "success",
            "message": "✅ Replies reloaded successfully",
            "old_count": old_count,
            "new_count": new_count,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"[-] Error reloading replies: {e}")
        return jsonify({
            "status": "error",
            "message": f"❌ Failed to reload replies: {str(e)}"
        }), 500

@app.route("/stats", methods=["GET"])
def stats():
    """Get detailed bot statistics"""
    return jsonify({
        "bot_statistics": {
            "global_reply_index": bot_state.reply_index,
            "total_replies_available": len(bot_state.load_replies()),
            "active_users": len(bot_state.user_states),
            "last_replies_reload": datetime.fromtimestamp(bot_state.last_reply_reload).isoformat() if bot_state.last_reply_reload else None
        },
        "user_activity": {
            user_id: {
                "reply_index": state["reply_index"],
                "last_active": datetime.fromtimestamp(state["last_active"]).isoformat()
            }
            for user_id, state in list(bot_state.user_states.items())[:10]  # Show max 10 users
        },
        "configuration": {
            "api_version": config.api_version,
            "has_access_token": bool(config.page_access_token),
            "verify_token_set": bool(config.verify_token)
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route("/test", methods=["GET"])
def test_endpoint():
    """Test endpoint to verify deployment"""
    return jsonify({
        "message": "🚀 Bot is deployed and running!",
        "test_successful": True,
        "timestamp": datetime.now().isoformat(),
        "ready_for_facebook": bool(config.page_access_token)
    })

# Background maintenance task
def background_maintenance():
    """Background task for cleanup and maintenance"""
    while True:
        time.sleep(300)  # Run every 5 minutes
        bot_state.cleanup_inactive_users()

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "❌ Endpoint not found", "available_endpoints": ["/", "/webhook", "/stats", "/test"]}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"[-] Internal server error: {error}")
    return jsonify({"error": "❌ Internal server error"}), 500

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 FACEBOOK MESSENGER AUTO-REPLY BOT")
    print("=" * 60)
    
    # Initialize replies (creates default if not exists)
    bot_state.load_replies(force_reload=True)
    
    # Configuration check
    if not config.page_access_token:
        print("⚠️  WARNING: Access token not found!")
        print("   Set PAGE_ACCESS_TOKEN environment variable")
        print("   Bot will start but won't send messages until token is configured")
    else:
        print("✅ Configuration loaded successfully")
        if os.getenv("PAGE_ACCESS_TOKEN"):
            print("✅ Token loaded from environment variable")
        else:
            print("✅ Token loaded from token.txt")
    
    print(f"🔗 Webhook URL: https://your-render-app.onrender.com/webhook")
    print(f"🔑 Verify Token: {config.verify_token}")
    print(f"📝 Replies: {len(bot_state.replies_cache)} loaded")
    print("=" * 60)
    
    # Start background maintenance
    maintenance_thread = threading.Thread(target=background_maintenance, daemon=True)
    maintenance_thread.start()
    
    # Start the Flask app
    port = int(os.getenv("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
