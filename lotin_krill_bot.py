# -*- coding: utf-8 -*-
"""
Created on Sat Jun 28 13:05:00 2025

@author: Asus
"""

from transliterate import to_cyrillic, to_latin

import telebot

TOKEN='7801959994:AAGtwyAxUYAXDgD4ojqSyFUS-NC8HZ3U0ls'
bot = telebot.TeleBot(TOKEN)

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
    
bot.infinity_polling()










