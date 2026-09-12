from transliterate import contains_cyrillic, to_cyrillic, to_latin
import telebot
from flask import Flask, request
import os
import threading
from datetime import datetime, timezone, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import watermark
import games

TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PRIVATE_STORAGE_CHANNEL_ID = int(os.getenv("PRIVATE_STORAGE_CHANNEL_ID", "0"))

if not PRIVATE_STORAGE_CHANNEL_ID:
    # Bu o'zgaruvchisiz "Fayl Saqlagich" funksiyasi ishlay olmaydi,
    # shuning uchun ishga tushishda ogohlantiramiz.
    print(
        "⚠️ PRIVATE_STORAGE_CHANNEL_ID muhit o'zgaruvchisi sozlanmagan! "
        "\"Fayl Saqlagich\" funksiyasi ishlamaydi."
    )

bot = telebot.TeleBot(TOKEN)
state = {}

# Foydalanuvchi fayl yuborayotgan vaqtdagi vaqtinchalik sessiya ma'lumotlari.
# Kalit: chat_id, qiymat: {"owner_id", "telegram_files", "channel_message_ids",
#                           "pin_code", "is_one_time", "expires_at", "expiry_label"}
pending_uploads = {}

# Media albom (bir nechta fayldan iborat xabar guruhi) elementlarini
# vaqtincha to'plash uchun bufer. Kalit: media_group_id
media_group_buffer = {}
MEDIA_GROUP_WAIT_SECONDS = 1.5

app = Flask(__name__)


def get_main_services_markup():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🇺🇿 Krill-Lotin", callback_data='krill_latin'),
        InlineKeyboardButton("🖼 Watermark — Mualliflik huquqi", callback_data='watermark')
    )
    markup.add(InlineKeyboardButton("📁 Fayl Saqlagich", callback_data='file_vault'))
    markup.add(InlineKeyboardButton("🎮 O'yinlar", callback_data='game:open'))
    return markup


games_controller = games.register(bot, get_main_services_markup, state)


def get_back_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data='back_to_main'))
    return markup


def get_link_settings_markup(chat_id):
    """Berilgan chat uchun vaqtinchalik sessiya holatiga mos Link Settings klaviaturasini quradi."""
    data = pending_uploads.get(chat_id, {})

    onetime_label = (
        "🔥 Bir martalik havola: ✅ Yoqilgan"
        if data.get("is_one_time")
        else "🔥 Bir martalik havola: ❌ O'chirilgan"
    )
    pin_label = (
        "🔐 PIN-kod: ✅ O'rnatilgan (o'zgartirish)"
        if data.get("pin_code")
        else "🔐 PIN-kod qo'yish"
    )
    expiry_label = f"⏳ Amal qilish muddati: {data.get('expiry_label', '♾️ Cheksiz')}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(onetime_label, callback_data='fv_toggle_onetime'))
    markup.add(InlineKeyboardButton(expiry_label, callback_data='fv_expiry_menu'))
    markup.add(InlineKeyboardButton(pin_label, callback_data='fv_set_pin'))
    markup.add(InlineKeyboardButton("✅ Havolani yaratish", callback_data='fv_generate_link'))
    markup.add(InlineKeyboardButton("❌ Bekor qilish", callback_data='fv_cancel'))
    return markup


def get_expiry_options_markup():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("1 kun", callback_data='fv_expiry_1'),
        InlineKeyboardButton("7 kun", callback_data='fv_expiry_7'),
        InlineKeyboardButton("30 kun", callback_data='fv_expiry_30'),
    )
    markup.add(InlineKeyboardButton("♾️ Cheksiz", callback_data='fv_expiry_none'))
    markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data='fv_settings_back'))
    return markup


def extract_file_info(msg):
    """Xabardagi faylning `file_id` va turini (photo/video/document/audio) aniqlaydi."""
    if msg.content_type == 'photo':
        return msg.photo[-1].file_id, 'photo'
    if msg.content_type == 'video':
        return msg.video.file_id, 'video'
    if msg.content_type == 'document':
        return msg.document.file_id, 'document'
    if msg.content_type == 'audio':
        return msg.audio.file_id, 'audio'
    return None, None


def start_link_settings(chat_id, owner_id, telegram_files, channel_message_ids):
    """
    Fayl(lar) yopiq kanalga muvaffaqiyatli forward qilingandan so'ng
    vaqtinchalik sessiyani yaratadi va foydalanuvchini Link Settings
    (havola sozlamalari) menyusiga o'tkazadi.
    """
    pending_uploads[chat_id] = {
        "owner_id": owner_id,
        "telegram_files": telegram_files,
        "channel_message_ids": channel_message_ids,
        "pin_code": None,
        "is_one_time": False,
        "expires_at": None,
        "expiry_label": "♾️ Cheksiz",
    }
    state[chat_id] = 'file_vault_settings'
    bot.send_message(
        chat_id,
        "✅ Fayl(lar) muvaffaqiyatli qabul qilindi va xavfsiz saqlandi!\n\n"
        "⚙️ Endi ushbu fayl uchun havola sozlamalarini tanlang:",
        reply_markup=get_link_settings_markup(chat_id)
    )


def handle_media_group_item(message):
    """
    Media albomning (bir nechta rasm/video birga yuborilgan xabar) har bir
    elementini darhol saqlash kanaliga forward qiladi va natijalarni
    `media_group_buffer`ga to'playdi. Barcha elementlar kelib bo'lgach
    (qisqa kutish vaqtidan so'ng), `finalize_media_group` chaqiriladi.
    """
    chat_id = message.chat.id
    group_id = message.media_group_id

    try:
        forwarded = bot.forward_message(PRIVATE_STORAGE_CHANNEL_ID, chat_id, message.message_id)
    except Exception as e:
        print(f"Xatolik: albom elementini saqlash kanaliga forward qilishda muammo: {e}")
        return

    file_id, file_type = extract_file_info(forwarded)
    if not file_id:
        return

    entry = media_group_buffer.get(group_id)
    if entry is None:
        entry = {
            "chat_id": chat_id,
            "owner_id": message.from_user.id,
            "telegram_files": [],
            "channel_message_ids": [],
            "timer": None,
        }
        media_group_buffer[group_id] = entry

    entry["telegram_files"].append({"file_id": file_id, "file_type": file_type})
    entry["channel_message_ids"].append(forwarded.message_id)

    if entry["timer"] is not None:
        entry["timer"].cancel()

    timer = threading.Timer(MEDIA_GROUP_WAIT_SECONDS, finalize_media_group, args=(group_id,))
    entry["timer"] = timer
    timer.start()


def finalize_media_group(group_id):
    """Albomning barcha elementlari yig'ib bo'lingach, Link Settings menyusini ochadi."""
    entry = media_group_buffer.pop(group_id, None)
    if entry is None:
        return
    start_link_settings(
        entry["chat_id"],
        entry["owner_id"],
        entry["telegram_files"],
        entry["channel_message_ids"],
    )


@bot.message_handler(commands=['start'])
def start_message(message):
    state[message.chat.id] = 'main'
    bot.send_message(
        message.chat.id,
        "Bot xizmatlaridan birini tanlang:",
        reply_markup=get_main_services_markup()
    )


@bot.callback_query_handler(func=lambda call: call.data in ['krill_latin', 'watermark', 'file_vault', 'back_to_main'])
def handle_menu_navigation(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if call.data == 'krill_latin':
        state[chat_id] = 'krill_latin'
        bot.edit_message_text(
            "📝 Matn kiriting:\n"
            f"{'✦ ' * 10}\n",
            chat_id,
            msg_id,
            reply_markup=get_back_markup()
        )
    elif call.data == 'watermark':
        state[chat_id] = 'watermark'
        bot.edit_message_text(
            "🖼 *Watermark — Mualliflik huquqi*\n\n"
            "📤 Himoyalamoqchi bo'lgan rasmni yuboring.\n"
            "✍️ Izoh (caption) qismiga watermark sifatida chiqishini xohlagan matnni yozing "
            "(masalan: kanalingiz nomi yoki istalgan matn).\n\n"
            "ℹ️ Izoh qoldirmasangiz, standart watermark matni qo'yiladi.",
            chat_id,
            msg_id,
            parse_mode="Markdown",
            reply_markup=get_back_markup()
        )
    elif call.data == 'file_vault':
        state[chat_id] = 'file_vault_upload'
        bot.edit_message_text(
            "📤 Saqlamoqchi bo'lgan faylingizni yuboring (rasm, video, hujjat yoki audio):",
            chat_id,
            msg_id,
            reply_markup=get_back_markup()
        )
    elif call.data == 'back_to_main':
        state[chat_id] = 'main'
        # Faqat tugma o'chadi, xabar qoladi
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
        bot.send_message(
            call.message.chat.id,
            "💼 Bot xizmatlaridan birini tanlang:\n",
            parse_mode="Markdown",
            reply_markup=get_main_services_markup()
        )


@bot.callback_query_handler(func=lambda call: call.data in [
    'fv_toggle_onetime', 'fv_set_pin', 'fv_expiry_menu', 'fv_expiry_1', 'fv_expiry_7',
    'fv_expiry_30', 'fv_expiry_none', 'fv_settings_back', 'fv_generate_link', 'fv_cancel'
])
def handle_file_vault_settings(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = pending_uploads.get(chat_id)

    if data is None:
        bot.answer_callback_query(
            call.id,
            "⚠️ Faol sessiya topilmadi. Iltimos, qaytadan fayl yuboring.",
            show_alert=True
        )
        return

    if call.data == 'fv_toggle_onetime':
        data["is_one_time"] = not data["is_one_time"]
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=get_link_settings_markup(chat_id))

    elif call.data == 'fv_expiry_menu':
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "⏳ Havola qancha muddat amal qilishini tanlang:",
            chat_id,
            msg_id,
            reply_markup=get_expiry_options_markup()
        )

    elif call.data in ('fv_expiry_1', 'fv_expiry_7', 'fv_expiry_30', 'fv_expiry_none'):
        days_map = {'fv_expiry_1': (1, "1 kun"), 'fv_expiry_7': (7, "7 kun"), 'fv_expiry_30': (30, "30 kun")}
        if call.data == 'fv_expiry_none':
            data["expires_at"] = None
            data["expiry_label"] = "♾️ Cheksiz"
        else:
            days, label = days_map[call.data]
            data["expires_at"] = datetime.now(timezone.utc) + timedelta(days=days)
            data["expiry_label"] = label
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "✅ Fayl(lar) muvaffaqiyatli qabul qilindi va xavfsiz saqlandi!\n\n"
            "⚙️ Endi ushbu fayl uchun havola sozlamalarini tanlang:",
            chat_id,
            msg_id,
            reply_markup=get_link_settings_markup(chat_id)
        )

    elif call.data == 'fv_settings_back':
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "✅ Fayl(lar) muvaffaqiyatli qabul qilindi va xavfsiz saqlandi!\n\n"
            "⚙️ Endi ushbu fayl uchun havola sozlamalarini tanlang:",
            chat_id,
            msg_id,
            reply_markup=get_link_settings_markup(chat_id)
        )

    elif call.data == 'fv_set_pin':
        state[chat_id] = 'file_vault_awaiting_pin'
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "🔐 4 tadan 8 tagacha raqamdan iborat PIN-kodni yuboring:",
            chat_id,
            msg_id,
            reply_markup=get_back_markup()
        )

    elif call.data == 'fv_generate_link':
        # Havola yaratish va MongoDB'ga yozish logikasi keyingi bosqichda qo'shiladi.
        bot.answer_callback_query(
            call.id,
            "🚧 Havola yaratish funksiyasi keyingi bosqichda qo'shiladi.",
            show_alert=True
        )

    elif call.data == 'fv_cancel':
        pending_uploads.pop(chat_id, None)
        state[chat_id] = 'main'
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "❌ Bekor qilindi.",
            chat_id,
            msg_id,
        )
        bot.send_message(
            chat_id,
            "💼 Bot xizmatlaridan birini tanlang:",
            reply_markup=get_main_services_markup()
        )


@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id

    if games_controller["process_text"](message):
        return

    if state.get(chat_id) == 'krill_latin':
        msg = message.text
        if contains_cyrillic(msg):
            answer = to_latin(msg)
        else:
            answer = to_cyrillic(msg)
        bot.send_message(
            chat_id,
            f"🧾 Matndan nusxa oling:\n\n"
            f"👉 `{answer}`\n"
            f"{'─' * 15}\n",
            parse_mode="Markdown",
            reply_markup=get_back_markup()
        )
    elif state.get(chat_id) == 'file_vault_awaiting_pin':
        pin = message.text.strip()
        if not pin.isdigit() or not (4 <= len(pin) <= 8):
            bot.send_message(
                chat_id,
                "⚠️ PIN-kod faqat 4 tadan 8 tagacha raqamdan iborat bo'lishi kerak. "
                "Qaytadan kiriting:",
                reply_markup=get_back_markup()
            )
            return

        data = pending_uploads.get(chat_id)
        if data is None:
            state[chat_id] = 'main'
            bot.send_message(
                chat_id,
                "⚠️ Faol sessiya topilmadi. Iltimos, qaytadan fayl yuboring.",
                reply_markup=get_main_services_markup()
            )
            return

        data["pin_code"] = pin
        state[chat_id] = 'file_vault_settings'
        bot.send_message(
            chat_id,
            "✅ PIN-kod muvaffaqiyatli o'rnatildi!\n\n⚙️ Havola sozlamalari:",
            reply_markup=get_link_settings_markup(chat_id)
        )
    elif state.get(chat_id) == 'main':
        bot.send_message(
            chat_id,
            "Bot xizmatlaridan birini tanlang:",
            reply_markup=get_main_services_markup()
        )


@bot.message_handler(content_types=['photo', 'document'])
def handle_watermark_upload(message):
    chat_id = message.chat.id
    if state.get(chat_id) == 'watermark':
        user_text = message.caption if message.caption else watermark.DEFAULT_WATERMARK_TEXT

        try:
            if message.content_type == 'photo':
                file_id = message.photo[-1].file_id
            elif message.content_type == 'document' and message.document.mime_type.startswith('image/'):
                file_id = message.document.file_id
            else:
                bot.send_message(
                    chat_id,
                    "⚠️ Iltimos, rasm formatidagi fayl yuboring.",
                    reply_markup=get_back_markup()
                )
                return

            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            img = watermark.open_image(downloaded_file)
            bio = watermark.apply_watermark(img, user_text)
            bot.send_photo(
                chat_id,
                bio,
                caption="✅ Watermark muvaffaqiyatli qo'shildi!",
                reply_markup=get_back_markup()
            )
        except Exception as e:
            print(f"Xatolik: {e}")
            bot.send_message(chat_id, "Xatolik yuz berdi.", reply_markup=get_back_markup())


@bot.message_handler(content_types=['photo', 'video', 'document', 'audio'])
def handle_file_vault_upload(message):
    chat_id = message.chat.id
    if state.get(chat_id) != 'file_vault_upload':
        return

    if message.media_group_id:
        # Media albom (bir nechta fayl birga yuborilgan) — har bir elementni
        # alohida qayta ishlab, hammasi yig'ilgach umumiy sessiya ochiladi.
        handle_media_group_item(message)
        return

    try:
        forwarded = bot.forward_message(PRIVATE_STORAGE_CHANNEL_ID, chat_id, message.message_id)
    except Exception as e:
        print(f"Xatolik: faylni saqlash kanaliga forward qilishda muammo: {e}")
        bot.send_message(
            chat_id,
            "❌ Faylni saqlashda xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=get_back_markup()
        )
        return

    file_id, file_type = extract_file_info(forwarded)
    if not file_id:
        bot.send_message(chat_id, "⚠️ Fayl turi qo'llab-quvvatlanmaydi.", reply_markup=get_back_markup())
        return

    start_link_settings(
        chat_id,
        message.from_user.id,
        [{"file_id": file_id, "file_type": file_type}],
        [forwarded.message_id],
    )


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