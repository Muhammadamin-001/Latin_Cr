
from transliterate import to_cyrillic, to_latin
import telebot
#from telebot import types
from flask import Flask, request
import os

TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

bot = telebot.TeleBot(TOKEN)
state={}
app = Flask(__name__)


@bot.message_handler(commands=['start'])
def send_wellcome(message):
    
    
    notice="\tMатн киритинг:\t 📥..."
    bot.send_message(message.chat.id, notice)

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    msg=message.text
    if msg.isascii():
        answer=to_cyrillic(msg)
    else:
        answer=to_latin(msg)
    bot.reply_to(message, f"`{answer}`", reply= "Markdown")



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










