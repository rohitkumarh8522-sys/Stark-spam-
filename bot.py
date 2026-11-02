import asyncio

# Python 3.14 compatibility fix for Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os
import json
import http.server
import socketserver
import threading
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Render Web Service Port Binding Fix ---
PORT = int(os.getenv("PORT", 10000))

class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

def run_http_server():
    try:
        with socketserver.TCPServer(("", PORT), HealthCheckHandler) as httpd:
            print(f"HTTP server running on port {PORT}")
            httpd.serve_forever()
    except Exception as e:
        print(f"HTTP server error: {e}")

# Start HTTP server in background thread so Render port scan succeeds
threading.Thread(target=run_http_server, daemon=True).start()
# ---------------------------------------------

# Safe environment variable parsing
api_id_raw = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
admin_id_raw = os.getenv("ADMIN_ID")

if not api_id_raw or not API_HASH or not BOT_TOKEN:
    print("❌ ERROR: API_ID, API_HASH, ya BOT_TOKEN environment variable me missing hai!")
    exit(1)

try:
    API_ID = int(api_id_raw)
except ValueError:
    print("❌ ERROR: API_ID ek valid number hona chahiye!")
    exit(1)

ADMIN_ID = int(admin_id_raw) if admin_id_raw else 0

DATA_FILE = "data.json"

DEFAULT_DATA = {
    "broadcast_message": "Hello friends! This is an automated message.",
    "interval": 60,
    "auto_reply": "Hello! I am currently busy, will reply soon.",
    "sessions": {},
    "active_tasks": {}
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_DATA
    return DEFAULT_DATA

def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving data: {e}")

db = load_data()

app = Client("master_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_main_menu():
    running_count = sum(1 for s in db["sessions"].values() if s.get("running"))
    total_accounts = len(db["sessions"])
    
    text = (
        f"✨ **Master Control Bot** ✨\n"
        f"👤 User Panel\n\n"
        f"📊 Accounts: {total_accounts} (Running: {running_count})\n"
        f"💬 Messages Sent: {db.get('total_sent', 0)}\n"
        f"⏱ Cycle: {db['interval']}s\n"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start All", callback_data="start_all"), InlineKeyboardButton("⏹ Stop All", callback_data="stop_all")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"), InlineKeyboardButton("🔑 Session Login", callback_data="login_session")],
        [InlineKeyboardButton("❌ Delete Account", callback_data="delete_account")]
    ])
    return text, keyboard

@app.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_cmd(client, message):
    text, kb = get_main_menu()
    await message.reply_text(text, reply_markup=kb)

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    
    if data == "settings":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Set Broadcast Msg", callback_data="set_msg")],
            [InlineKeyboardButton("⏱ Set Time Interval", callback_data="set_time")],
            [InlineKeyboardButton("🤖 Set Auto-Reply", callback_data="set_autoreply")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
        ])
        await callback_query.message.edit_text("⚙️ **Bot Settings Panel**", reply_markup=kb)
        
    elif data == "back_home":
        text, kb = get_main_menu()
        await callback_query.message.edit_text(text, reply_markup=kb)
        
    elif data == "login_session":
        await callback_query.message.reply_text(
            "Apna Pyrogram String Session bhejein:\nFormat: `/addsession <STRING_SESSION>`"
        )
    elif data == "delete_account":
        if not db["sessions"]:
            await callback_query.answer("Koi account added nahi hai!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(f"Remove Session {i+1}", callback_data=f"del_{k}")] for i, k in enumerate(db["sessions"].keys())]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
        await callback_query.message.edit_text("Select account to delete:", reply_markup=InlineKeyboardMarkup(buttons))
        
    elif data.startswith("del_"):
        s_key = data.split("_")[1]
        if s_key in db["sessions"]:
            db["sessions"].pop(s_key)
            save_data(db)
            await callback_query.answer("Account removed successfully!", show_alert=True)
        text, kb = get_main_menu()
        await callback_query.message.edit_text(text, reply_markup=kb)

    elif data == "start_all":
        await callback_query.answer("Starting all sessions...", show_alert=True)
        for s_string in db["sessions"].keys():
            if not db["sessions"][s_string].get("running"):
                db["sessions"][s_string]["running"] = True
                task = asyncio.create_task(run_broadcaster(s_string))
                db["active_tasks"][s_string] = task
        save_data(db)
        text, kb = get_main_menu()
        await callback_query.message.edit_text(text, reply_markup=kb)

    elif data == "stop_all":
        await callback_query.answer("Stopping all sessions...", show_alert=True)
        for s_string, task in db["active_tasks"].items():
            task.cancel()
            db["sessions"][s_string]["running"] = False
        db["active_tasks"] = {}
        save_data(db)
        text, kb = get_main_menu()
        await callback_query.message.edit_text(text, reply_markup=kb)

@app.on_message(filters.command("addsession") & filters.user(ADMIN_ID))
async def add_session_cmd(client, message):
    try:
        args = message.text.split(" ", 1)
        if len(args) < 2:
            await message.reply_text("Please provide session string. Example: `/addsession 1Bw...`")
            return
        session_str = args[1].strip()
        
        user_client = Client("temp_sess", api_id=API_ID, api_hash=API_HASH, session_string=session_str)
        async with user_client:
            me = await user_client.get_me()
            
        db["sessions"][session_str] = {"running": False, "phone": me.phone_number}
        save_data(db)
        await message.reply_text(f"✅ Account Added Successfully!\nPhone: `{me.phone_number}`")
    except Exception as e:
        await message.reply_text(f"❌ Invalid Session String: {e}")

async def run_broadcaster(session_string):
    try:
        user_app = Client(f"session_{session_string[:10]}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
        async with user_app:
            @user_app.on_message(filters.private & ~filters.me)
            async def handle_private(c, msg):
                auto_msg = db.get("auto_reply")
                if auto_msg:
                    await msg.reply_text(auto_msg)

            while db["sessions"].get(session_string, {}).get("running", False):
                msg_text = db.get("broadcast_message")
                interval = db.get("interval", 60)
                
                async for dialog in user_app.get_dialogs():
                    if dialog.chat.type.name in ["GROUP", "SUPERGROUP"]:
                        try:
                            await user_app.send_message(dialog.chat.id, msg_text)
                            db["total_sent"] = db.get("total_sent", 0) + 1
                            save_data(db)
                            await asyncio.sleep(2)
                        except Exception:
                            continue
                            
                await asyncio.sleep(interval)
    except Exception as e:
        print(f"Error in session: {e}")
        if session_string in db["sessions"]:
            db["sessions"][session_string]["running"] = False
            save_data(db)

async def main():
    await app.start()
    print("🤖 Master Bot started successfully!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
