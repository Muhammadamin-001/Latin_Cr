
from transliterate import to_cyrillic, to_latin
import telebot
from flask import Flask, request
import os

#TOKEN='7801959994:AAGtwyAxUYAXDgD4ojqSyFUS-NC8HZ3U0ls'
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = telebot.TeleBot(TOKEN)

app = Flask(__name__)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    notice="Assalomu aleykum!\nQuyidagi amaliyot uchun: Krill-Lotin, Lotin-Krill."
    notice+="\tmatn kiriting:"
    bot.reply_to(message, notice)


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    msg=message.text
    if msg.isascii():
        answer=to_cyrillic(msg)
    else:
        answer=to_latin(msg)
    bot.reply_to(message, answer)
    
# bot.infinity_polling()

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

# Just to test server
@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":

    PORT = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=PORT)









