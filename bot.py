import os
import telebot
import random
import time
import threading
import logging
import requests
import io
import html
from PIL import Image, ImageDraw, ImageFont
from http.server import HTTPServer, BaseHTTPRequestHandler
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)

# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
BOT_TOKEN = "8902638130:AAGleUenJUvVyELpyW5Tu-8fDI7bUOlyg7M"
ADMIN_ID = 8872100978
UPI_ID = "molu.pandey@freecharge"
BOT_NAME = "DAVO CASINO"

MIN_BET = 10.0
MAX_BET = 10000.0

try:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=15)
    logging.info("Cleaned pending webhooks successfully.")
except Exception as e:
    logging.warning(f"Failed to clear webhook: {e}")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)

USER_BALANCES = {}
USER_UPI_IDS = {}
USER_WAITING_STATE = {}
PVP_MATCHES = {}
ACTIVE_GAME_SESSIONS = {}
ESCROW_DEALS = {}
ACTIVE_GROUP_USERS = set()

BOT_ACTIVE = True

# -------------------------------------------------------------
# DECORATORS & HELPERS
# -------------------------------------------------------------
def safe_name(name):
    return html.escape(name if name else "User")

def restricted_command(func):
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id != ADMIN_ID and not BOT_ACTIVE:
            bot.reply_to(message, "⚠️ <b>Bot is currently stopped by the Admin.</b> Please try again later.")
            return
        return func(message, *args, **kwargs)
    return wrapper

def restricted_callback(func):
    def wrapper(call, *args, **kwargs):
        user_id = call.from_user.id
        if user_id != ADMIN_ID and not BOT_ACTIVE:
            bot.answer_callback_query(call.id, "❌ Bot is currently stopped by Admin!", show_alert=True)
            return
        return func(call, *args, **kwargs)
    return wrapper

def get_balance(user_id):
    if user_id not in USER_BALANCES:
        USER_BALANCES[user_id] = 0.0
    return USER_BALANCES[user_id]

def parse_pvp_args(args, user_id):
    if len(args) < 1:
        return None, None, "⚠️ Please specify an amount! (Example: <code>/bowl 100</code> or <code>/bowl 100 3</code>)"

    balance = get_balance(user_id)
    val1 = args[0].lower()
    val2 = args[1].lower() if len(args) > 1 else None

    amount = None
    rounds = 1

    try:
        if len(args) >= 2:
            p1, p2 = float(args[0]), float(args[1])
            if 1 <= p1 <= 5 and p1.is_integer() and p2 > 5:
                rounds, amount = int(p1), p2
            elif 1 <= p2 <= 5 and p2.is_integer() and p1 > 5:
                rounds, amount = int(p2), p1
            else:
                amount, rounds = p1, int(p2) if p2.is_integer() else 1
        elif len(args) == 1:
            if val1 == "all":
                amount = balance
            else:
                amount = float(args[0])
            rounds = 1
    except Exception:
        pass

    if amount is None or amount <= 0:
        return None, None, "❌ Invalid Amount!"
    if amount < MIN_BET:
        return None, None, f"❌ Minimum bet is ₹{MIN_BET:.0f}!"
    if amount > MAX_BET and amount != balance:
        return None, None, f"❌ Maximum bet is ₹{MAX_BET:.0f}!"
    if balance < amount or balance == 0:
        return None, None, "❌ <b>Insufficient Balance!</b> You don't have enough balance."
    if rounds < 1 or rounds > 5:
        return None, None, "❌ Rounds must be between 1 and 5!"

    return amount, rounds, None

@bot.message_handler(func=lambda msg: True, content_types=['text', 'dice', 'photo', 'video', 'sticker'])
def track_active_users(message):
    if message.chat.type in ['group', 'supergroup']:
        ACTIVE_GROUP_USERS.add(message.from_user.id)
    return False

# -------------------------------------------------------------
# START, STOP & ADMIN COMMANDS
# -------------------------------------------------------------
@bot.message_handler(commands=['start'])
def send_start(message):
    try:
        global BOT_ACTIVE
        user_id = message.from_user.id
        user_name = safe_name(message.from_user.full_name)

        if user_id == ADMIN_ID:
            BOT_ACTIVE = True
            markup = InlineKeyboardMarkup()
            btn_status = InlineKeyboardButton("🔴 Stop Bot", callback_data="admin_toggle_bot")
            markup.add(btn_status)
            bot.reply_to(message, f"🟢 <b>Bot is now STARTED & ACTIVE!</b>\n\n🎰 <b>{BOT_NAME} ADMIN PANEL</b>\nStatus: ACTIVE\n\n• <code>/addbal user_id amount</code>", reply_markup=markup)
        else:
            if not BOT_ACTIVE:
                bot.reply_to(message, "⚠️ <b>Bot is currently stopped by the Admin.</b> Please try again later.")
                return
            bot.reply_to(message, f"🎰 Welcome <b>{user_name}</b> to <b>{BOT_NAME}</b>!\n\n🎮 Type <code>/games</code> to see available games.")
    except Exception as e:
        logging.error(f"Start Error: {e}")

@bot.message_handler(commands=['stop'])
def send_stop(message):
    try:
        global BOT_ACTIVE
        user_id = message.from_user.id
        if user_id == ADMIN_ID:
            BOT_ACTIVE = False
            markup = InlineKeyboardMarkup()
            btn_status = InlineKeyboardButton("🟢 Start Bot", callback_data="admin_toggle_bot")
            markup.add(btn_status)
            bot.reply_to(message, f"🔴 <b>Bot is now STOPPED!</b>\n\nNo users can play games now. Type <code>/start</code> to resume.", reply_markup=markup)
        else:
            bot.reply_to(message, "❌ You are not authorized to stop the bot.")
    except Exception as e:
        logging.error(f"Stop Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_toggle_bot")
def handle_admin_toggle(call):
    global BOT_ACTIVE
    try:
        if call.from_user.id != ADMIN_ID: return
        BOT_ACTIVE = not BOT_ACTIVE
        status_text = "🟢 ACTIVE" if BOT_ACTIVE else "🔴 STOPPED"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔴 Stop Bot" if BOT_ACTIVE else "🟢 Start Bot", callback_data="admin_toggle_bot"))
        bot.edit_message_text(f"🎰 <b>{BOT_NAME} ADMIN PANEL</b>\n\nStatus: {status_text}", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id, f"Bot status changed to {status_text}")
    except Exception as e:
        logging.error(f"Toggle Error: {e}")

@bot.message_handler(commands=['addbal'])
def admin_add_balance(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target_id, amount = int(args[1]), float(args[2])
        USER_BALANCES[target_id] = get_balance(target_id) + amount
        bot.reply_to(message, f"✅ Added ₹{amount:.2f} to <code>{target_id}</code>")
        try:
            bot.send_message(target_id, f"🎉 <b>₹{amount:.2f} credited to your wallet!</b>\n💳 Current Balance: ₹{get_balance(target_id):.2f}")
        except Exception: pass
    except Exception:
        bot.reply_to(message, "⚠️ Format: <code>/addbal user_id amount</code>")

# -------------------------------------------------------------
# RAIN SYSTEM COMMAND (/rain amount members)
# -------------------------------------------------------------
@bot.message_handler(commands=['rain'])
@restricted_command
def cmd_rain(message):
    try:
        if message.chat.type not in ['group', 'supergroup']:
            bot.reply_to(message, "⚠️ <b>/rain command can only be used in groups!</b>")
            return

        user_id = message.from_user.id
        args = message.text.split()[1:]

        if len(args) < 2:
            bot.reply_to(message, "⚠️ Usage: <code>/rain 1000 5</code> (Amount, Members)")
            return

        try:
            total_amount = float(args[0])
            num_members = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Invalid format! Example: <code>/rain 1000 5</code>")
            return

        if total_amount <= 0:
            bot.reply_to(message, "❌ Rain amount must be greater than 0!")
            return

        if not (1 <= num_members <= 100):
            bot.reply_to(message, "❌ Members count must be between 1 and 100!")
            return

        balance = get_balance(user_id)
        if balance < total_amount:
            bot.reply_to(message, f"❌ <b>Insufficient Balance!</b> You have ₹{balance:.2f}, but you are trying to rain ₹{total_amount:.2f}.")
            return

        eligible_users = list(ACTIVE_GROUP_USERS)
        if user_id in eligible_users:
            eligible_users.remove(user_id)

        if len(eligible_users) < num_members:
            bot.reply_to(message, f"❌ Not enough active users in the group! Currently tracked active users: {len(eligible_users)}. Try a smaller member count.")
            return

        USER_BALANCES[user_id] -= total_amount

        selected_users = random.sample(eligible_users, num_members)
        amount_per_user = total_amount / num_members

        winners_text = []
        for uid in selected_users:
            USER_BALANCES[uid] = get_balance(uid) + amount_per_user
            try:
                chat_member = bot.get_chat_member(message.chat.id, uid)
                name = safe_name(chat_member.user.first_name)
            except Exception:
                name = f"User {uid}"
            winners_text.append(f"• {name}: <b>₹{amount_per_user:.2f}</b>")

        rain_report = (
            f"🌧️ <b>MONEY RAIN EVENT!</b> 🌧️\n\n"
            f"👤 <b>Rain By:</b> {safe_name(message.from_user.first_name)}\n"
            f"💰 <b>Total Rain:</b> ₹{total_amount:.2f}\n"
            f"👥 <b>Distributed To:</b> {num_members} random members\n"
            f"💸 <b>Per Person:</b> ₹{amount_per_user:.2f}\n\n"
            f"🏆 <b>Lucky Winners:</b>\n" + "\n".join(winners_text)
        )

        bot.reply_to(message, rain_report, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Rain Error: {e}")
        bot.reply_to(message, "⚠️ An error occurred while processing rain.")

# -------------------------------------------------------------
# BOT FUND (/hb)
# -------------------------------------------------------------
@bot.message_handler(commands=['hb'])
@restricted_command
def send_bot_fund(message):
    bot.reply_to(
        message,
        "<b>❄️ Bot Fund = $1,471.81</b>\n"
        "<b>🏛 Bet active!</b>\n"
        "<b>🧿 Davo Verse</b>"
    )

# -------------------------------------------------------------
# DEPOSIT & WITHDRAWAL SYSTEM
# -------------------------------------------------------------
@bot.message_handler(commands=['deposit'])
@restricted_command
def cmd_deposit(message):
    if message.chat.type != 'private':
        markup = InlineKeyboardMarkup()
        bot_username = bot.get_me().username
        markup.add(InlineKeyboardButton("📥 Open Private Chat to Deposit", url=f"https://t.me/{bot_username}?start=deposit"))
        bot.reply_to(message, "⚠️ <b>Please use the /deposit command in our private chat for security and privacy!</b>", reply_markup=markup)
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📥 Enter Deposit Amount", callback_data="dep_amount"))
    
    bot.reply_to(
        message,
        f"💳 <b>DEPOSIT MONEY</b>\n\n"
        f"📍 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
        f"📲 Click the button below to enter your amount, make the payment, and send the screenshot here.",
        reply_markup=markup
    )

@bot.message_handler(commands=['withdraw'])
@restricted_command
def cmd_withdraw(message):
    if message.chat.type != 'private':
        markup = InlineKeyboardMarkup()
        bot_username = bot.get_me().username
        markup.add(InlineKeyboardButton("📤 Open Private Chat to Withdraw", url=f"https://t.me/{bot_username}?start=withdraw"))
        bot.reply_to(message, "⚠️ <b>Please use the /withdraw command in our private chat for security and privacy!</b>", reply_markup=markup)
        return

    user_id = message.from_user.id
    current_upi = USER_UPI_IDS.get(user_id, "Not Set")
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✏️ Set / Change UPI", callback_data="wd_set_upi"),
        InlineKeyboardButton("📤 Withdraw Amount", callback_data="wd_amount")
    )
    
    bot.reply_to(
        message,
        f"💸 <b>WITHDRAWAL PANEL</b>\n\n"
        f"💳 Your Saved UPI: <code>{current_upi}</code>\n"
        f"💰 Balance: ₹{get_balance(user_id):.2f}\n\n"
        f"Use the buttons below to set your UPI or withdraw funds:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data in ["dep_amount", "wd_set_upi", "wd_amount"])
@restricted_callback
def handle_wallet_callbacks(call):
    user_id = call.from_user.id
    if call.data == "dep_amount":
        USER_WAITING_STATE[user_id] = "waiting_deposit"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📥 How much would you like to deposit? Type the amount (e.g., <code>500</code>):")
    elif call.data == "wd_set_upi":
        USER_WAITING_STATE[user_id] = "waiting_upi"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "✏️ Type your valid UPI ID (e.g., <code>username@okhdfcbank</code>):")
    elif call.data == "wd_amount":
        if user_id not in USER_UPI_IDS:
            bot.answer_callback_query(call.id, "❌ Please set your UPI ID first!", show_alert=True)
            return
        USER_WAITING_STATE[user_id] = "waiting_withdraw"
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"📤 How much amount do you want to withdraw? (Balance: ₹{get_balance(user_id):.2f}):")

@bot.message_handler(content_types=['photo'])
def handle_deposit_screenshot(message):
    try:
        user_id = message.from_user.id
        if user_id != ADMIN_ID and not BOT_ACTIVE:
            return

        if message.chat.type != 'private':
            return

        file_id = message.photo[-1].file_id
        user_name = safe_name(message.from_user.full_name)
        username = f"@{message.from_user.username}" if message.from_user.username else "No Username"

        caption_text = (
            f"📥 <b>NEW DEPOSIT SCREENSHOT RECEIVED!</b>\n\n"
            f"👤 User: {user_name} ({username})\n"
            f"🆔 ID: <code>{user_id}</code>\n\n"
            f"👉 Use this command to add balance:\n"
            f"<code>/addbal {user_id} [amount]</code>"
        )

        bot.send_photo(ADMIN_ID, file_id, caption=caption_text, parse_mode="HTML")
        bot.reply_to(message, "✅ <b>Screenshot successfully sent to Admin!</b>\nAdmin will verify and add balance to your wallet.")
        
        if user_id in USER_WAITING_STATE:
            del USER_WAITING_STATE[user_id]

    except Exception as e:
        logging.error(f"Screenshot Error: {e}")

# -------------------------------------------------------------
# ESCROW & TIP SYSTEM
# -------------------------------------------------------------
@bot.message_handler(commands=['escrow'])
@restricted_command
def cmd_escrow(message):
    try:
        if not message.reply_to_message:
            bot.reply_to(message, "⚠️ Please reply to someone's message with: <code>/escrow 50</code>")
            return
        
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Usage: <code>/escrow 50</code> (by replying)")
            return
            
        amount = float(args[1])
        sender_id = message.from_user.id
        receiver_id = message.reply_to_message.from_user.id
        receiver_name = safe_name(message.reply_to_message.from_user.first_name)

        if sender_id == receiver_id:
            bot.reply_to(message, "❌ You cannot do escrow with yourself!")
            return
        if get_balance(sender_id) < amount:
            bot.reply_to(message, "❌ You do not have enough balance in your wallet!")
            return

        USER_BALANCES[sender_id] -= amount
        deal_id = f"escrow_{int(time.time())}"
        ESCROW_DEALS[deal_id] = {
            "sender": sender_id,
            "receiver": receiver_id,
            "amount": amount
        }

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Release", callback_data=f"esc_rel_{deal_id}"),
            InlineKeyboardButton("❌ Refund", callback_data=f"esc_ref_{deal_id}")
        )

        bot.reply_to(
            message,
            f"🤝 <b>ESCROW CREATED!</b>\n\n"
            f"👤 From: {safe_name(message.from_user.first_name)}\n"
            f"👤 To: {receiver_name}\n"
            f"💰 Amount: ₹{amount:.2f}\n\n"
            f"<i>Funds are on hold. Click Release or Refund once work is completed.</i>",
            reply_markup=markup
        )
    except Exception as e:
        logging.error(f"Escrow Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("esc_"))
@restricted_callback
def handle_escrow_callbacks(call):
    data = call.data.split("_")
    action = data[1]
    deal_id = "_".join(data[2:])
    user_id = call.from_user.id

    if deal_id not in ESCROW_DEALS:
        bot.answer_callback_query(call.id, "❌ Deal expired or completed!", show_alert=True)
        return

    deal = ESCROW_DEALS[deal_id]
    if user_id != deal["sender"] and user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Only sender or admin can perform this action!", show_alert=True)
        return

    if action == "rel":
        USER_BALANCES[deal["receiver"]] = get_balance(deal["receiver"]) + deal["amount"]
        bot.edit_message_text(f"✅ <b>ESCROW RELEASED!</b>\n💰 ₹{deal['amount']:.2f} successfully transferred.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    else:
        USER_BALANCES[deal["sender"]] = get_balance(deal["sender"]) + deal["amount"]
        bot.edit_message_text(f"❌ <b>ESCROW REFUNDED!</b>\n💰 ₹{deal['amount']:.2f} returned to sender.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    
    del ESCROW_DEALS[deal_id]

@bot.message_handler(commands=['tip'])
@restricted_command
def cmd_tip(message):
    try:
        if not message.reply_to_message:
            bot.reply_to(message, "⚠️ Please reply to someone's message with <code>/tip 50</code>!")
            return
            
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Usage: <code>/tip 50</code> (by replying)")
            return
            
        amount = float(args[1])
        sender_id = message.from_user.id
        receiver_id = message.reply_to_message.from_user.id
        receiver_name = safe_name(message.reply_to_message.from_user.first_name)

        if sender_id == receiver_id:
            bot.reply_to(message, "❌ You cannot tip yourself!")
            return
        if get_balance(sender_id) < amount:
            bot.reply_to(message, "❌ Insufficient balance for tip!")
            return

        USER_BALANCES[sender_id] -= amount
        USER_BALANCES[receiver_id] = get_balance(receiver_id) + amount

        bot.reply_to(
            message,
            f"🎁 <b>TIP SUCCESSFUL!</b>\n\n"
            f"👤 From: {safe_name(message.from_user.first_name)}\n"
            f"👤 To: {receiver_name}\n"
            f"💰 Amount: <b>₹{amount:.2f}</b> sent!"
        )
    except Exception as e:
        logging.error(f"Tip Error: {e}")

@bot.message_handler(func=lambda msg: msg.from_user.id in USER_WAITING_STATE)
def handle_text_inputs(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID and not BOT_ACTIVE:
        return

    if message.chat.type != 'private':
        return
        
    state = USER_WAITING_STATE[user_id]
    text = message.text.strip()

    if state == "waiting_upi":
        USER_UPI_IDS[user_id] = text
        del USER_WAITING_STATE[user_id]
        bot.reply_to(message, f"✅ <b>UPI saved successfully!</b>\n💳 UPI: <code>{text}</code>")

    elif state == "waiting_deposit":
        try:
            amount = float(text)
            bot.reply_to(
                message,
                f"📥 <b>DEPOSIT AMOUNT NOTIFIED (₹{amount:.2f})</b>\n\n"
                f"📍 Send payment to UPI: <code>{UPI_ID}</code>\n\n"
                f"⚠️ <i>Please send the payment **Screenshot** right here in chat so the admin can verify.</i>"
            )
        except ValueError:
            bot.reply_to(message, "❌ Invalid amount!")

    elif state == "waiting_withdraw":
        try:
            amount = float(text)
            del USER_WAITING_STATE[user_id]
            balance = get_balance(user_id)
            if amount < 50:
                bot.reply_to(message, "❌ Minimum withdrawal is ₹50!")
                return
            if balance < amount:
                bot.reply_to(message, "❌ Insufficient balance!")
                return
            
            upi = USER_UPI_IDS.get(user_id)
            if not upi or upi == "Not Set":
                bot.reply_to(message, "❌ Please set your UPI ID first using /withdraw -> Set UPI")
                return

            USER_BALANCES[user_id] -= amount
            
            bot.reply_to(message, f"📤 <b>Withdrawal Request Placed!</b>\n💰 Amount: ₹{amount:.2f}\n💳 UPI: <code>{upi}</code>\n\nAdmin will send payment soon.")
            
            user_name = safe_name(message.from_user.full_name)
            username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
            
            admin_msg = (
                f"💸 <b>NEW WITHDRAWAL REQUEST!</b>\n\n"
                f"👤 User: {user_name} ({username})\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"💰 Amount: <b>₹{amount:.2f}</b>\n"
                f"💳 UPI ID: <code>{upi}</code>"
            )

            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("✅ Approve", callback_data=f"wd_app_{user_id}_{amount}"),
                InlineKeyboardButton("❌ Reject & Refund", callback_data=f"wd_rej_{user_id}_{amount}")
            )

            bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML", reply_markup=markup)

        except ValueError:
            bot.reply_to(message, "❌ Invalid amount!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("wd_app_") or call.data.startswith("wd_rej_"))
@restricted_callback
def handle_withdrawal_actions(call):
    try:
        data = call.data.split("_")
        action = data[1]
        target_user_id = int(data[2])
        amount = float(data[3])

        if action == "app":
            bot.edit_message_text(
                f"{call.message.text}\n\n<b>Status: ✅ APPROVED & PAID BY ADMIN</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML"
            )
            bot.answer_callback_query(call.id, "Withdrawal Approved!")
            try:
                bot.send_message(
                    target_user_id,
                    f"🎉 <b>Your withdrawal of ₹{amount:.2f} has been APPROVED!</b>\n"
                    f"Payment has been successfully sent to your UPI."
                )
            except Exception:
                pass

        elif action == "rej":
            USER_BALANCES[target_user_id] = get_balance(target_user_id) + amount
            bot.edit_message_text(
                f"{call.message.text}\n\n<b>Status: ❌ REJECTED & REFUNDED</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML"
            )
            bot.answer_callback_query(call.id, "Withdrawal Rejected & Refunded!")
            try:
                bot.send_message(
                    target_user_id,
                    f"❌ <b>Your withdrawal request of ₹{amount:.2f} was REJECTED by Admin.</b>\n"
                    f"Amount has been refunded back to your wallet."
                )
            except Exception:
                pass

    except Exception as e:
        logging.error(f"Withdrawal Action Error: {e}")
        bot.answer_callback_query(call.id, "❌ Error processing request!", show_alert=True)

# -------------------------------------------------------------
# MENU & WALLET SYSTEM
# -------------------------------------------------------------
@bot.message_handler(commands=['games', 'help'])
@restricted_command
def send_games_list(message):
    bot.reply_to(
        message, 
        f"🎰 <b>{BOT_NAME} MENU</b> 🎰\n\n"
        f"💳 <b>WALLET:</b> Balance: <code>/wallet</code> | Deposit: <code>/deposit</code> | Withdraw: <code>/withdraw</code>\n"
        f"❄️ Bot Fund: <code>/hb</code> | Rain: <code>/rain 1000 5</code> | Escrow: <code>/escrow 50</code> | Tip: <code>/tip 50</code>\n\n"
        f"⚔️ <b>PVP / PVB GAMES:</b> <code>/dice 100</code> | <code>/bowl 100</code> | <code>/basketball 100</code> | <code>/dart 100</code>\n\n"
        f"🕹️ <b>SOLO GAMES:</b>\n"
        f"🎲 <b>Dice Rush:</b> <code>/dr 100 low</code>\n"
        f"🚀 <b>Limbo:</b> <code>/limbo 100 2.0</code>\n"
        f"🎰 <b>Slots:</b> <code>/slots 100 3</code>"
    )

@bot.message_handler(commands=['wallet', 'bal'])
@restricted_command
def check_wallet(message):
    user_id = message.from_user.id
    bot.reply_to(message, f"💳 <b>WALLET BALANCE:</b> ₹{get_balance(user_id):.2f}\n🆔 ID: <code>{user_id}</code>")

# -------------------------------------------------------------
# SOLO GAMES
# -------------------------------------------------------------
@bot.message_handler(commands=['dr', 'dicerush'])
@restricted_command
def cmd_dice_rush(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()[1:]
        valid_choices = ["low", "high", "even", "odd"]
        
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Format: <code>/dr 100 low</code>")
            return
            
        val1, val2 = args[0].lower(), args[1].lower()
        balance = get_balance(user_id)
        amount, choice = None, None

        if val1 == "all":
            amount = balance
            if val2 in valid_choices: choice = val2
        elif val2 == "all":
            amount = balance
            if val1 in valid_choices: choice = val1
        else:
            for val in [val1, val2]:
                if val in valid_choices: choice = val
                else:
                    try: amount = float(val)
                    except ValueError: pass

        if choice is None or amount is None or amount <= 0:
            bot.reply_to(message, "❌ Invalid Amount or Choice!")
            return
        if amount < MIN_BET:
            bot.reply_to(message, f"❌ Minimum bet is ₹{MIN_BET:.0f}!")
            return
        if balance < amount:
            bot.reply_to(message, "❌ Insufficient Balance!")
            return

        USER_BALANCES[user_id] -= amount
        msg = bot.send_dice(message.chat.id, emoji="🎲")
        dice_val = msg.dice.value

        win = False
        if choice == "low" and dice_val in [1, 2, 3]: win = True
        elif choice == "high" and dice_val in [4, 5, 6]: win = True
        elif choice == "even" and dice_val % 2 == 0: win = True
        elif choice == "odd" and dice_val % 2 != 0: win = True

        if win:
            payout = amount * 1.95
            USER_BALANCES[user_id] += payout
            res_text = f"🎉 <b>YOU WON!</b>\n🎲 Outcome: <b>{dice_val}</b>\n💰 Won: ₹{payout:.2f}"
        else:
            res_text = f"💔 <b>YOU LOST!</b>\n🎲 Outcome: <b>{dice_val}</b>\n🔻 Lost: ₹{amount:.2f}"

        bot.reply_to(message, f"{res_text}\n💳 Balance: ₹{get_balance(user_id):.2f}")
    except Exception as e: logging.error(f"DR Error: {e}")

@bot.message_handler(commands=['limbo'])
@restricted_command
def cmd_limbo(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()[1:]
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Usage: <code>/limbo 100 2.0</code>")
            return
            
        amount, target = float(args[0]), float(args[1])
        balance = get_balance(user_id)
        if balance < amount:
            bot.reply_to(message, "❌ Insufficient balance!")
            return
        
        USER_BALANCES[user_id] -= amount

        actual_multiplier = round(random.uniform(1.00, max(5.0, target * 1.5)), 2)
        win = actual_multiplier >= target

        if win:
            payout = amount * target
            USER_BALANCES[user_id] += payout
            net_profit = payout - amount
            res_text = f"WON! +₹{net_profit:.2f}"
        else:
            res_text = f"CRASHED! -₹{amount:.2f}"
            
        updated_bal = get_balance(user_id)

        img = Image.new('RGB', (600, 350), color=(15, 15, 25))
        d = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("arial.ttf", 30)
            font_small = ImageFont.truetype("arial.ttf", 20)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        d.text((30, 30), "🚀 DAVO LIMBO GAME", fill=(0, 255, 204), font=font_large)
        d.text((30, 80), f"Player: {message.from_user.first_name}", fill=(255, 255, 255), font=font_small)
        d.text((30, 120), f"Bet Amount: ₹{amount:.2f}", fill=(255, 255, 255), font=font_small)
        d.text((30, 160), f"Target: {target}x  |  Hit: {actual_multiplier}x", fill=(255, 215, 0), font=font_small)
        
        result_color = (0, 255, 0) if win else (255, 69, 0)
        d.text((30, 210), f"Result: {res_text}", fill=result_color, font=font_large)
        d.text((30, 270), f"Balance: ₹{updated_bal:.2f}", fill=(200, 200, 200), font=font_small)

        bio = io.BytesIO()
        bio.name = 'limbo_result.png'
        img.save(bio, 'PNG')
        bio.seek(0)

        caption_text = (
            f"🚀 <b>DAVO CASINO - LIMBO</b> 🚀\n\n"
            f"👤 Player: {safe_name(message.from_user.first_name)}\n"
            f"💸 Bet: <b>₹{amount:.2f}</b> | Target: <b>{target}x</b>\n"
            f"📊 Multiplier: <b>{actual_multiplier}x</b>\n"
            f"{'🎉 <b>WON! Payout: ₹' + f'{payout:.2f}</b>' if win else '💥 <b>CRASHED! Lost: ₹' + f'{amount:.2f}</b>'}\n\n"
            f"💳 <b>New Balance: ₹{updated_bal:.2f}</b>"
        )

        bot.send_photo(message.chat.id, bio, caption=caption_text, parse_mode="HTML")

    except Exception as e: 
        logging.error(f"Limbo Error: {e}")
        bot.reply_to(message, f"⚠️ An error occurred: {e}")

@bot.message_handler(commands=['slots', 'slot'])
@restricted_command
def cmd_slots(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()[1:]
        amount = float(args[0]) if len(args) > 0 else 10.0
        balance = get_balance(user_id)
        if balance < amount:
            bot.reply_to(message, "❌ Insufficient balance!")
            return
        USER_BALANCES[user_id] -= amount
        msg = bot.send_dice(message.chat.id, emoji="🎰")
        val = msg.dice.value
        if val in [1, 22, 43, 64]:
            payout = amount * 5.0
            USER_BALANCES[user_id] += payout
            bot.reply_to(message, f"🎰 <b>JACKPOT!</b> Won ₹{payout:.2f}")
        else:
            bot.reply_to(message, f"💔 <b>LOST!</b>")
    except Exception as e: logging.error(f"Slots Error: {e}")

# -------------------------------------------------------------
# PVP & PVB GAMES ENGINE
# -------------------------------------------------------------
def create_pvp_challenge(message, game_type, emoji):
    user_id = message.from_user.id
    args = message.text.split()[1:]

    amount, rounds, err = parse_pvp_args(args, user_id)
    if err:
        bot.reply_to(message, f"{err}\n\n<b>Usage:</b> <code>/{game_type} 100</code> or <code>/{game_type} 100 3</code>")
        return

    USER_BALANCES[user_id] -= amount
    match_id = f"pvp_{game_type}_{user_id}_{int(time.time())}"

    PVP_MATCHES[match_id] = {
        "game": game_type,
        "emoji": emoji,
        "p1_id": user_id,
        "p1_name": safe_name(message.from_user.first_name),
        "p2_id": None,
        "p2_name": None,
        "amount": amount,
        "rounds": rounds,
        "p1_scores": [],
        "p2_scores": [],
        "turn": "p1",
        "mode": None
    }

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("⚔️ Accept Match", callback_data=f"pvp_accept_{match_id}"),
        InlineKeyboardButton("🤖 Play with Bot", callback_data=f"pvp_bot_{match_id}")
    )
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data=f"pvp_cancel_{match_id}"))

    bot.reply_to(
        message,
        f"⚔️ <b>{game_type.upper()} MATCH!</b> {emoji}\n\n"
        f"👤 <b>Challenger:</b> {safe_name(message.from_user.first_name)}\n"
        f"🔄 <b>Rounds:</b> {rounds} | 💰 <b>Bet:</b> ₹{amount:.2f}\n\n"
        f"<i>Click below to accept or play with Bot.</i>",
        reply_markup=markup
    )

@bot.message_handler(commands=['dice'])
@restricted_command
def cmd_pvp_dice(message):
    create_pvp_challenge(message, "dice", "🎲")

@bot.message_handler(commands=['bowl', 'bowling'])
@restricted_command
def cmd_pvp_bowl(message):
    create_pvp_challenge(message, "bowl", "🎳")

@bot.message_handler(commands=['basketball', 'bb'])
@restricted_command
def cmd_pvp_bb(message):
    create_pvp_challenge(message, "basketball", "🏀")

@bot.message_handler(commands=['dart'])
@restricted_command
def cmd_pvp_dart(message):
    create_pvp_challenge(message, "dart", "🎯")

@bot.callback_query_handler(func=lambda call: call.data.startswith("pvp_"))
@restricted_callback
def handle_pvp_callbacks(call):
    try:
        data = call.data.split("_")
        action = data[1]
        match_id = "_".join(data[2:])
        user_id = call.from_user.id

        if match_id not in PVP_MATCHES:
            bot.answer_callback_query(call.id, "❌ Match expired or already finished!", show_alert=True)
            return

        match = PVP_MATCHES[match_id]

        if action == "cancel":
            if user_id != match["p1_id"] and user_id != ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ Only challenger can cancel this match!", show_alert=True)
                return
            USER_BALANCES[match["p1_id"]] += match["amount"]
            bot.edit_message_text(f"❌ <b>Match Cancelled & Refunded!</b>", chat_id=call.message.chat.id, message_id=call.message.message_id)
            del PVP_MATCHES[match_id]
            return

        elif action == "bot":
            if user_id != match["p1_id"]:
                bot.answer_callback_query(call.id, "❌ Only the challenger can choose Bot!", show_alert=True)
                return
            match["p2_id"] = "BOT"
            match["p2_name"] = "🤖 CASINO BOT"
            match["mode"] = "bot"
            
            ACTIVE_GAME_SESSIONS[match["p1_id"]] = match_id

            bot.edit_message_text(
                f"🤖 <b>MATCH STARTED: {match['p1_name']} vs BOT</b> {match['emoji']}\n"
                f"💰 Bet: ₹{match['amount']:.2f} | Rounds: {match['rounds']}\n\n"
                f"👉 <b>{match['p1_name']} ki baari hai!</b> Apne saare rounds ke throws chat me khud karein (Round 1/{match['rounds']}).",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            bot.answer_callback_query(call.id)
            return

        elif action == "accept":
            if user_id == match["p1_id"]:
                bot.answer_callback_query(call.id, "❌ You cannot accept your own match!", show_alert=True)
                return
            if get_balance(user_id) < match["amount"]:
                bot.answer_callback_query(call.id, "❌ Insufficient balance to accept match!", show_alert=True)
                return
            
            USER_BALANCES[user_id] -= match["amount"]
            match["p2_id"] = user_id
            match["p2_name"] = safe_name(call.from_user.first_name)
            match["mode"] = "pvp"

            ACTIVE_GAME_SESSIONS[match["p1_id"]] = match_id

            bot.edit_message_text(
                f"⚔️ <b>PVP MATCH STARTED!</b> {match['emoji']}\n"
                f"👤 <b>{match['p1_name']}</b> vs 👤 <b>{match['p2_name']}</b>\n"
                f"💰 Bet: ₹{match['amount']:.2f} | Rounds: {match['rounds']}\n\n"
                f"👉 <b>{match['p1_name']} ki baari hai!</b> Apne saare rounds ke throws chat me karein (Round 1/{match['rounds']}).",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            bot.answer_callback_query(call.id)
            return

    except Exception as e:
        logging.error(f"PvP CB Error: {e}")

@bot.message_handler(content_types=['dice'])
def handle_game_dice(message):
    user_id = message.from_user.id
    if user_id not in ACTIVE_GAME_SESSIONS:
        return

    match_id = ACTIVE_GAME_SESSIONS[user_id]
    if match_id not in PVP_MATCHES:
        del ACTIVE_GAME_SESSIONS[user_id]
        return

    match = PVP_MATCHES[match_id]
    dice_emoji = message.dice.emoji
    dice_value = message.dice.value

    if dice_emoji != match["emoji"]:
        return

    chat_id = message.chat.id

    if match["turn"] == "p1" and user_id == match["p1_id"]:
        match["p1_scores"].append(dice_value)
        current_r = len(match["p1_scores"])

        if current_r < match["rounds"]:
            bot.reply_to(message, f"🎲 {match['p1_name']} Throw (Round {current_r}/{match['rounds']})\n👉 Agla throw karein!")
        else:
            if match["mode"] == "bot":
                bot.reply_to(message, f"✅ <b>{match['p1_name']} ke saare rounds poore ho gaye!</b>\n🤖 Ab Bot apna animation ke sath throw kar raha hai...")
                del ACTIVE_GAME_SESSIONS[user_id]
                
                time.sleep(1.5)
                for r in range(1, match["rounds"] + 1):
                    bot.send_message(chat_id, f"🤖 <b>{match['p2_name']} Throw (Round {r}/{match['rounds']})</b>")
                    sent_bot_dice = bot.send_dice(chat_id, emoji=match["emoji"])
                    b_score = sent_bot_dice.dice.value
                    match["p2_scores"].append(b_score)
                    time.sleep(3.5)

                p1_total = sum(match["p1_scores"])
                p2_total = sum(match["p2_scores"])

                if p1_total > p2_total:
                    payout = match["amount"] * 2
                    USER_BALANCES[match["p1_id"]] += payout
                    res_text = f"🏆 <b>{match['p1_name']} WON THE MATCH!</b>\n\nScores:\n👤 {match['p1_name']}: {p1_total} ({match['p1_scores']})\n🤖 {match['p2_name']}: {p2_total} ({match['p2_scores']})\n\n💰 Won: <b>₹{payout:.2f}</b>"
                elif p2_total > p1_total:
                    res_text = f"🤖 <b>BOT WON THE MATCH!</b>\n\nScores:\n👤 {match['p1_name']}: {p1_total} ({match['p1_scores']})\n🤖 {match['p2_name']}: {p2_total} ({match['p2_scores']})"
                else:
                    USER_BALANCES[match["p1_id"]] += match["amount"]
                    res_text = f"🤝 <b>MATCH DRAW!</b> Amount refunded.\n\nScores:\n👤 {match['p1_name']}: {p1_total} | 🤖 {match['p2_name']}: {p2_total}"

                bot.send_message(chat_id, res_text)
                del PVP_MATCHES[match_id]

            elif match["mode"] == "pvp":
                match["turn"] = "p2"
                del ACTIVE_GAME_SESSIONS[match["p1_id"]]
                ACTIVE_GAME_SESSIONS[match["p2_id"]] = match_id
                bot.reply_to(message, f"✅ <b>{match['p1_name']} ke saare rounds poore ho gaye!</b>\n👉 <b>Ab {match['p2_name']} ki baari hai!</b> Apne rounds ke throws chat me karein (Round 1/{match['rounds']}).")

    elif match["turn"] == "p2" and user_id == match["p2_id"]:
        match["p2_scores"].append(dice_value)
        current_r = len(match["p2_scores"])

        if current_r < match["rounds"]:
            bot.reply_to(message, f"🎲 {match['p2_name']} Throw (Round {current_r}/{match['rounds']})\n👉 Agla throw karein!")
        else:
            del ACTIVE_GAME_SESSIONS[user_id]

            p1_total = sum(match["p1_scores"])
            p2_total = sum(match["p2_scores"])

            if p1_total > p2_total:
                payout = match["amount"] * 2
                USER_BALANCES[match["p1_id"]] += payout
                res_text = f"🏆 <b>{match['p1_name']} WON THE MATCH!</b>\n\nScores:\n👤 {match['p1_name']}: {p1_total} ({match['p1_scores']})\n👤 {match['p2_name']}: {p2_total} ({match['p2_scores']})\n\n💰 Won: <b>₹{payout:.2f}</b>"
            elif p2_total > p1_total:
                payout = match["amount"] * 2
                USER_BALANCES[match["p2_id"]] += payout
                res_text = f"🏆 <b>{match['p2_name']} WON THE MATCH!</b>\n\nScores:\n👤 {match['p1_name']}: {p1_total} ({match['p1_scores']})\n👤 {match['p2_name']}: {p2_total} ({match['p2_scores']})\n\n💰 Won: <b>₹{payout:.2f}</b>"
            else:
                USER_BALANCES[match["p1_id"]] += match["amount"]
                USER_BALANCES[match["p2_id"]] += match["amount"]
                res_text = f"🤝 <b>MATCH DRAW!</b> Amount refunded to both.\n\nScores:\n👤 {match['p1_name']}: {p1_total} | 👤 {match['p2_name']}: {p2_total}"

            bot.send_message(chat_id, res_text)
            del PVP_MATCHES[match_id]

# -------------------------------------------------------------
# KEEP ALIVE SERVER & BOT STARTUP
# -------------------------------------------------------------
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    do_GET = lambda s: (s.send_response(200), s.send_header('Content-type', 'text/plain'), s.end_headers(), s.wfile.write(b"DAVO CASINO BOT ONLINE"))
    do_HEAD = lambda s: (s.send_response(200), s.end_headers())

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"🌐 Web Server Running on Port {port}")
    server.serve_forever()

def start_polling():
    print("⚡ Starting Telegram Bot Polling...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logging.error(f"Polling Crashed: {e}")
            time.sleep(1)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_polling, daemon=True)
    bot_thread.start()
    run_web_server()
