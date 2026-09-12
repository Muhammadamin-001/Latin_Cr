from transliterate import contains_cyrillic, to_cyrillic, to_latin
import telebot
from flask import Flask, request
import os
import threading
import asyncio
import secrets
from datetime import datetime, timezone, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo.errors import DuplicateKeyError
import watermark
import games
import database

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

# ---------------------------------------------------------------------------
# `database.py`dagi asinxron (`async`) funksiyalarni sinxron pyTelegramBotAPI
# handlerlari ichida xavfsiz chaqirish uchun doimiy background event loop.
# ---------------------------------------------------------------------------

_background_loop = asyncio.new_event_loop()


def _run_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


_background_thread = threading.Thread(
    target=_run_background_loop, args=(_background_loop,), daemon=True
)
_background_thread.start()


def run_async(coro):
    """
    `database.py`dagi `async` funksiyalarni sinxron bot handlerlari ichida
    xavfsiz ishga tushiradi. Barcha chaqiruvlar bitta doimiy background
    event loop threadida bajariladi — shu sababli MongoDB (`motor`) clienti
    bilan mos keladi va "different event loop" xatoliklari oldini oladi.
    """
    future = asyncio.run_coroutine_threadsafe(coro, _background_loop)
    return future.result()


try:
    run_async(database.connect_to_mongo())
except Exception as e:
    print(
        f"⚠️ MongoDB'ga ulanishda muammo yuz berdi (bot baribir ishga tushadi): {e}"
    )

try:
    BOT_USERNAME = bot.get_me().username
except Exception as e:
    print(f"⚠️ Bot username'ini olishda muammo yuz berdi: {e}")
    BOT_USERNAME = None


state = {}

# Foydalanuvchi fayl yuborayotgan vaqtdagi vaqtinchalik sessiya ma'lumotlari.
# Kalit: chat_id, qiymat: {"owner_id", "telegram_files", "channel_message_ids",
#                           "pin_code", "is_one_time", "expires_at", "expiry_label"}
pending_uploads = {}

# Deep-link (`/start file_<TOKEN>`) orqali PIN-kod tekshirilayotgan foydalanuvchilar
# uchun vaqtinchalik sessiya. Kalit: chat_id, qiymat: {"token": str}
pending_downloads = {}

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


def get_link_settings_text(chat_id):
    """Joriy vaqtinchalik sessiya holatiga mos sozlamalar xulosa matnini quradi."""
    data = pending_uploads.get(chat_id, {})
    onetime_status = "✅ Yoqilgan" if data.get("is_one_time") else "❌ O'chirilgan"
    pin_status = "✅ O'rnatilgan" if data.get("pin_code") else "❌ O'rnatilmagan"
    expiry_status = data.get("expiry_label", "♾️ Cheksiz")

    return (
        "✅ Fayl(lar) muvaffaqiyatli qabul qilindi va xavfsiz saqlandi!\n\n"
        "⚙️ *Havola sozlamalari:*\n"
        f"💣 Bir martalik yuklash: {onetime_status}\n"
        f"🔐 PIN-kod: {pin_status}\n"
        f"⏳ Amal qilish muddati: {expiry_status}\n\n"
        "Quyidagi tugmalar orqali sozlamalarni o'zgartiring:"
    )


def get_link_settings_markup(chat_id):
    """File Link Configuration Menu — havola yaratishdan oldingi sozlamalar klaviaturasi."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔐 PIN-kod o'rnatish", callback_data='fv_set_pin'))
    markup.add(InlineKeyboardButton("💣 Bir martalik yuklash", callback_data='fv_toggle_onetime'))
    markup.add(InlineKeyboardButton("⏳ Amal qilish muddati", callback_data='fv_expiry_menu'))
    markup.add(InlineKeyboardButton("🚀 Havolani yaratish", callback_data='fv_generate_link'))
    markup.add(InlineKeyboardButton("❌ Bekor qilish", callback_data='fv_cancel'))
    return markup


def get_expiry_options_markup():
    """Amal qilish muddatini tanlash uchun ichki (inline) sozlamalar submenyusi."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("1 soat", callback_data='fv_expiry_1h'),
        InlineKeyboardButton("24 soat", callback_data='fv_expiry_24h'),
    )
    markup.row(
        InlineKeyboardButton("7 kun", callback_data='fv_expiry_7d'),
        InlineKeyboardButton("♾️ Cheksiz", callback_data='fv_expiry_none'),
    )
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
    vaqtinchalik sessiyani yaratadi va foydalanuvchini File Link
    Configuration Menu'ga (havola sozlamalari) o'tkazadi.
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
        get_link_settings_text(chat_id),
        parse_mode="Markdown",
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


def generate_and_send_link(chat_id, msg_id, data):
    """
    "🚀 Havolani yaratish" bosilganda chaqiriladi:
      1) `secrets.token_urlsafe(8)` bilan noyob token yaratadi.
      2) Fayl yozuvini `database.create_file_record()` orqali MongoDB'ga saqlaydi
         (juda kam ehtimollik bilan token takrorlansa, yangi token bilan qayta urinadi).
      3) Yakuniy ulashish havolasini va sozlamalar xulosasini foydalanuvchiga yuboradi.
    """
    max_attempts = 5
    saved_token = None

    for _ in range(max_attempts):
        candidate_token = secrets.token_urlsafe(8)
        try:
            run_async(
                database.create_file_record(
                    owner_id=data["owner_id"],
                    telegram_files=data["telegram_files"],
                    channel_message_ids=data["channel_message_ids"],
                    file_id_str=candidate_token,
                    pin_code=data.get("pin_code"),
                    is_one_time=data.get("is_one_time", False),
                    expires_at=data.get("expires_at"),
                )
            )
            saved_token = candidate_token
            break
        except DuplicateKeyError:
            # Ehtimoli juda past, lekin token band bo'lib chiqsa — yangisini sinaymiz.
            continue
        except Exception as e:
            print(f"Xatolik: fayl yozuvini MongoDB'ga saqlashda muammo: {e}")
            bot.edit_message_text(
                "❌ Havola yaratishda xatolik yuz berdi. Iltimos, birozdan so'ng qaytadan urinib ko'ring.",
                chat_id,
                msg_id,
            )
            return

    if saved_token is None:
        bot.edit_message_text(
            "❌ Noyob havola yaratib bo'lmadi. Iltimos, qaytadan urinib ko'ring.",
            chat_id,
            msg_id,
        )
        return

    username_part = BOT_USERNAME or "SizningBotingiz"
    link = f"https://t.me/{username_part}?start=file_{saved_token}"

    onetime_text = "✅ Ha" if data.get("is_one_time") else "❌ Yo'q"
    pin_text = "✅ O'rnatilgan" if data.get("pin_code") else "❌ Yo'q"
    expiry_text = data.get("expiry_label", "♾️ Cheksiz")

    recap = (
        "🎉 *Havola muvaffaqiyatli yaratildi!*\n\n"
        f"🔗 Havola: `{link}`\n\n"
        "📋 *Sozlamalar xulosasi:*\n"
        f"💣 Bir martalik yuklash: {onetime_text}\n"
        f"🔐 PIN-kod: {pin_text}\n"
        f"⏳ Amal qilish muddati: {expiry_text}"
    )

    pending_uploads.pop(chat_id, None)
    state[chat_id] = 'main'

    bot.edit_message_text(recap, chat_id, msg_id, parse_mode="Markdown")
    bot.send_message(
        chat_id,
        "💼 Bot xizmatlaridan birini tanlang:",
        reply_markup=get_main_services_markup()
    )


def deliver_files(chat_id, file_doc):
    """
    Fayl hujjatidagi (`stored_files`) barcha `telegram_files` elementlarini
    ularning turiga (photo/video/document/audio) mos metod orqali
    foydalanuvchiga yuboradi.
    """
    sender_map = {
        'photo': bot.send_photo,
        'video': bot.send_video,
        'document': bot.send_document,
        'audio': bot.send_audio,
    }
    for item in file_doc.get("telegram_files", []):
        file_type = item.get("file_type")
        file_id = item.get("file_id")
        sender = sender_map.get(file_type, bot.send_document)
        try:
            sender(chat_id, file_id)
        except Exception as e:
            print(f"Xatolik: faylni yuborishda muammo ({file_type}, {file_id}): {e}")


def complete_file_delivery(chat_id, token, file_doc):
    """
    PIN tekshiruvi (agar kerak bo'lsa) muvaffaqiyatli o'tgandan so'ng chaqiriladi:
    fayl(lar)ni yuboradi, `download_count`ni oshiradi va bir martalik bo'lsa
    faylni avtomatik faolsizlantiradi (bularning barchasi `increment_download`
    ichida amalga oshiriladi).
    """
    deliver_files(chat_id, file_doc)

    try:
        run_async(database.increment_download(token))
    except Exception as e:
        print(f"Xatolik: yuklab olishlar sonini oshirishda muammo: {e}")

    bot.send_message(chat_id, "✅ Fayl(lar) muvaffaqiyatli yuborildi!")


def handle_deep_link_file(chat_id, token):
    """
    `/start file_<TOKEN>` chuqur havolasi (deep link) orqali kelgan so'rovni
    qayta ishlaydi: tokenni MongoDB'dan qidiradi, faollik va muddatni
    tekshiradi, kerak bo'lsa PIN-kod so'raydi, so'ng faylni yetkazib beradi.
    """
    try:
        file_doc = run_async(database.get_file_by_token(token))
    except Exception as e:
        print(f"Xatolik: tokenni MongoDB'dan qidirishda muammo: {e}")
        bot.send_message(chat_id, "⚠️ Ushbu havola mavjud emas yoki o'chirilgan.")
        return

    if not file_doc:
        # `get_file_by_token` faqat `is_active: True` bo'lgan yozuvlarni qaytaradi,
        # shuning uchun topilmaslik ham "mavjud emas", ham "o'chirilgan" holatini qamrab oladi.
        bot.send_message(chat_id, "⚠️ Ushbu havola mavjud emas yoki o'chirilgan.")
        return

    expires_at = file_doc.get("expires_at")
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            # Ehtiyot chorasi: agar biror sabab bilan naive datetime qaytsa,
            # uni UTC deb hisoblaymiz (baza har doim UTC'da yozadi).
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            bot.send_message(chat_id, "⚠️ Ushbu havolaning amal qilish muddati tugagan.")
            return

    if file_doc.get("pin_code"):
        pending_downloads[chat_id] = {"token": token}
        state[chat_id] = 'awaiting_download_pin'
        bot.send_message(
            chat_id,
            "🔒 Ushbu fayl PIN-kod bilan himoyalangan. PIN-kodni kiriting:"
        )
        return

    complete_file_delivery(chat_id, token, file_doc)


@bot.message_handler(commands=['start'])
def start_message(message):
    chat_id = message.chat.id

    # `/start file_<TOKEN>` ko'rinishidagi chuqur havola (deep link) payload'ini ajratib olamiz.
    parts = message.text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    if payload.startswith("file_"):
        token = payload[len("file_"):]
        handle_deep_link_file(chat_id, token)
        return

    state[chat_id] = 'main'
    bot.send_message(
        chat_id,
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
    'fv_toggle_onetime', 'fv_set_pin', 'fv_expiry_menu', 'fv_expiry_1h', 'fv_expiry_24h',
    'fv_expiry_7d', 'fv_expiry_none', 'fv_settings_back', 'fv_generate_link', 'fv_cancel'
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
        bot.edit_message_text(
            get_link_settings_text(chat_id),
            chat_id,
            msg_id,
            parse_mode="Markdown",
            reply_markup=get_link_settings_markup(chat_id)
        )

    elif call.data == 'fv_expiry_menu':
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "⏳ Havola qancha muddat amal qilishini tanlang:",
            chat_id,
            msg_id,
            reply_markup=get_expiry_options_markup()
        )

    elif call.data in ('fv_expiry_1h', 'fv_expiry_24h', 'fv_expiry_7d', 'fv_expiry_none'):
        expiry_map = {
            'fv_expiry_1h': (timedelta(hours=1), "1 soat"),
            'fv_expiry_24h': (timedelta(hours=24), "24 soat"),
            'fv_expiry_7d': (timedelta(days=7), "7 kun"),
        }
        if call.data == 'fv_expiry_none':
            data["expires_at"] = None
            data["expiry_label"] = "♾️ Cheksiz"
        else:
            delta, label = expiry_map[call.data]
            data["expires_at"] = datetime.now(timezone.utc) + delta
            data["expiry_label"] = label
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            get_link_settings_text(chat_id),
            chat_id,
            msg_id,
            parse_mode="Markdown",
            reply_markup=get_link_settings_markup(chat_id)
        )

    elif call.data == 'fv_settings_back':
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            get_link_settings_text(chat_id),
            chat_id,
            msg_id,
            parse_mode="Markdown",
            reply_markup=get_link_settings_markup(chat_id)
        )

    elif call.data == 'fv_set_pin':
        state[chat_id] = 'file_vault_awaiting_pin'
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "🔐 4 xonali raqamli PIN-kodni kiriting:",
            chat_id,
            msg_id,
            reply_markup=get_back_markup()
        )

    elif call.data == 'fv_generate_link':
        bot.answer_callback_query(call.id)
        generate_and_send_link(chat_id, msg_id, data)

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
        if not pin.isdigit() or len(pin) != 4:
            bot.send_message(
                chat_id,
                "⚠️ PIN-kod aynan 4 ta raqamdan iborat bo'lishi kerak. Qaytadan kiriting:",
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
            "✅ PIN-kod muvaffaqiyatli o'rnatildi!\n\n" + get_link_settings_text(chat_id),
            parse_mode="Markdown",
            reply_markup=get_link_settings_markup(chat_id)
        )
    elif state.get(chat_id) == 'awaiting_download_pin':
        pending = pending_downloads.get(chat_id)
        if pending is None:
            state[chat_id] = 'main'
            bot.send_message(
                chat_id,
                "⚠️ Faol sessiya topilmadi. Havolani qaytadan oching.",
                reply_markup=get_main_services_markup()
            )
            return

        token = pending["token"]
        try:
            file_doc = run_async(database.get_file_by_token(token))
        except Exception as e:
            print(f"Xatolik: tokenni qayta tekshirishda muammo: {e}")
            file_doc = None

        if not file_doc:
            pending_downloads.pop(chat_id, None)
            state[chat_id] = 'main'
            bot.send_message(chat_id, "⚠️ Ushbu havola mavjud emas yoki o'chirilgan.")
            return

        entered_pin = message.text.strip()
        if entered_pin != file_doc.get("pin_code"):
            bot.send_message(chat_id, "❌ PIN-kod noto'g'ri. Qaytadan urinib ko'ring:")
            return

        pending_downloads.pop(chat_id, None)
        state[chat_id] = 'main'
        complete_file_delivery(chat_id, token, file_doc)
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