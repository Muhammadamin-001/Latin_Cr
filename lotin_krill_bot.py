from transliterate import to_cyrillic, to_latin
import telebot
from flask import Flask, request
import os
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
<<<<<<< HEAD
import Hazil_rasm
=======
>>>>>>> ac37f28da8cd05911fe26a51c54caf87b37a0c4b

TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = telebot.TeleBot(TOKEN)
state = {}

app = Flask(__name__)

def get_main_services_markup():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🇺🇿 Krill-Lotin", callback_data='krill_latin'),
        InlineKeyboardButton("🖼️ Rasmga matn", callback_data='hazil_rasm')
    )
    return markup

def get_back_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data='back_to_main'))
    return markup

@bot.message_handler(commands=['start'])
def start_message(message):
    state[message.chat.id] = 'main'
    bot.send_message(
        message.chat.id,
        "Bot xizmatlaridan birini tanlang:",
        reply_markup=get_main_services_markup()
    )

@bot.callback_query_handler(func=lambda call: call.data in ['krill_latin', 'hazil_rasm', 'back_to_main'])
def handle_menu_navigation(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    if call.data == 'krill_latin':
        state[chat_id] = 'krill_latin'
        bot.edit_message_text(
            "Matn kiriting:",
            chat_id,
            msg_id,
            reply_markup=get_back_markup()
        )
    elif call.data == 'hazil_rasm':
        state[chat_id] = 'hazil_rasm'
        bot.edit_message_text(
            "Rasm va tagiga matn yozib yuboring. Matnni qo'shib rasmga effekt beraman! ✨",
            chat_id,
            msg_id,
            reply_markup=get_back_markup()
        )
    elif call.data == 'back_to_main':
        state[chat_id] = 'main'
        bot.edit_message_text(
            "Bot xizmatlaridan birini tanlang:",
            chat_id,
            msg_id,
            reply_markup=get_main_services_markup()
        )

@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    
    if state.get(chat_id) == 'krill_latin':
        msg = message.text
        if msg.isascii():
            answer = to_cyrillic(msg)
        else:
            answer = to_latin(msg)
        bot.send_message(
            chat_id,
            f"`{answer}`",
            parse_mode="Markdown",
            reply_markup=get_back_markup()
        )
    elif state.get(chat_id) == 'main':
        bot.send_message(
            chat_id,
            "Bot xizmatlaridan birini tanlang:",
            reply_markup=get_main_services_markup()
        )

<<<<<<< HEAD
@bot.message_handler(content_types=['photo', 'document'])
def handle_photo_or_document(message):
    chat_id = message.chat.id
    if state.get(chat_id) == 'hazil_rasm':
        user_text = message.caption if message.caption else "DIQQAT! SOXTA VIDEO USTASI"
        user_text = Hazil_rasm.clean_text(user_text)
=======
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    msg=message.text
    if msg.isascii():
        answer=to_cyrillic(msg)
    else:
        answer=to_latin(msg)
    bot.reply_to(message, f"`{answer}`", parse_mode="Markdown")
>>>>>>> ac37f28da8cd05911fe26a51c54caf87b37a0c4b

        try:
            if message.content_type == 'photo':
                file_id = message.photo[-1].file_id
            elif message.content_type == 'document' and message.document.mime_type.startswith('image/'):
                file_id = message.document.file_id
            else:
                return

            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            img = Hazil_rasm.open_image(downloaded_file)
            img = Hazil_rasm.apply_effects(img)
            bio = Hazil_rasm.draw_caption(img, user_text)
            bot.send_photo(chat_id, bio, caption="Tayyor! 🚀", reply_markup=get_back_markup())
        except Exception as e:
            print(f"Xatolik: {e}")
            bot.send_message(chat_id, "Xatolik yuz berdi.", reply_markup=get_back_markup())

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=PORT)