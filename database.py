"""
Fayllar ombori (File Vault) uchun MongoDB ma'lumotlar bazasi moduli.

Ushbu modul `motor` (asinxron MongoDB drayveri) yordamida MongoDB'ga ulanishni,
`stored_files` to'plamini (collection) va u bilan ishlash uchun yordamchi
funksiyalarni ta'minlaydi.

MUHIM: quyidagi funksiyalarning barchasi `async def` ko'rinishida yozilgan.
Ularni chaqirish uchun asinxron muhitdan foydalaning, masalan:

    import asyncio
    asyncio.run(connect_to_mongo())

yoki mavjud `asyncio` event loop ichida `await` orqali chaqiring.
"""

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

logger = logging.getLogger("file_vault.database")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Sozlamalar (Configuration)
# ---------------------------------------------------------------------------

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "file_vault_db")
STORED_FILES_COLLECTION = "stored_files"

if not MONGO_URI:
    # Dastur ishga tushishidan oldin muhit o'zgaruvchisi mavjudligini tekshiramiz.
    logger.warning(
        "⚠️ MONGO_URI muhit o'zgaruvchisi topilmadi. "
        "MongoDB'ga ulanishdan oldin uni Railway/serverda sozlang!"
    )

# ---------------------------------------------------------------------------
# Global holat (client va database obyektlari)
# ---------------------------------------------------------------------------

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def get_client() -> AsyncIOMotorClient:
    """Mavjud bo'lsa global MongoDB clientini qaytaradi, aks holda yangisini yaratadi."""
    global _client
    if _client is None:
        if not MONGO_URI:
            raise RuntimeError(
                "MONGO_URI muhit o'zgaruvchisi o'rnatilmagan. MongoDB'ga ulanib bo'lmaydi."
            )
        _client = AsyncIOMotorClient(MONGO_URI)
        logger.info("🔌 MongoDB client yaratildi.")
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """Global database obyektini qaytaradi (kerak bo'lsa yaratadi)."""
    global _db
    if _db is None:
        _db = get_client()[MONGO_DB_NAME]
    return _db


def get_stored_files_collection() -> AsyncIOMotorCollection:
    """`stored_files` to'plamiga (collection) havolani qaytaradi."""
    return get_database()[STORED_FILES_COLLECTION]


async def connect_to_mongo() -> AsyncIOMotorDatabase:
    """
    MongoDB'ga ulanishni o'rnatadi, ulanish ishlayotganini tekshiradi (ping)
    va zarur indekslarni yaratadi. Dastur ishga tushganda bir marta chaqiring.
    """
    db = get_database()
    try:
        # Ulanish haqiqatan ishlayotganini tekshirish uchun "ping" yuboramiz.
        await get_client().admin.command("ping")
        logger.info("✅ MongoDB'ga muvaffaqiyatli ulanildi. Baza: %s", MONGO_DB_NAME)
    except PyMongoError as exc:
        logger.error("❌ MongoDB'ga ulanishda xatolik yuz berdi: %s", exc)
        raise

    await create_indexes()
    return db


async def close_mongo_connection() -> None:
    """MongoDB ulanishini yopadi. Dastur to'xtaganda chaqiring."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("🔒 MongoDB ulanishi yopildi.")


async def create_indexes() -> None:
    """
    `stored_files` to'plami uchun zarur indekslarni yaratadi:
      - `file_id_str` bo'yicha UNIKAL indeks — har bir tokenning
        takrorlanmasligini ta'minlaydi va tez qidiruvga imkon beradi.
      - `expires_at` bo'yicha TTL indeks — muddati o'tgan fayl yozuvlarini
        MongoDB avtomatik ravishda o'chirib tashlaydi.
      - `owner_id` bo'yicha oddiy indeks — foydalanuvchining fayllarini
        tezroq topish uchun.
    """
    collection = get_stored_files_collection()
    try:
        await collection.create_index(
            [("file_id_str", ASCENDING)],
            name="uniq_file_id_str",
            unique=True,
        )
        # expireAfterSeconds=0 => hujjat aynan `expires_at` vaqtiga yetganda o'chadi.
        # `expires_at` qiymati `None` bo'lgan hujjatlarga TTL ta'sir qilmaydi.
        await collection.create_index(
            [("expires_at", ASCENDING)],
            name="ttl_expires_at",
            expireAfterSeconds=0,
        )
        await collection.create_index(
            [("owner_id", ASCENDING)],
            name="idx_owner_id",
        )
        logger.info("📇 `stored_files` uchun indekslar muvaffaqiyatli tayyorlandi.")
    except PyMongoError as exc:
        logger.error("❌ Indekslarni yaratishda xatolik yuz berdi: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar (Helper functions)
# ---------------------------------------------------------------------------


def generate_file_token(length: int = 8) -> str:
    """
    Fayl havolasi uchun (`start=file_TOKEN`) mo'ljallangan noyob, URL-xavfsiz
    token yaratadi. Standart uzunlik — 8 (`secrets.token_urlsafe(8)`).
    """
    return secrets.token_urlsafe(length)


async def create_file_record(
    owner_id: int,
    telegram_files: List[Dict[str, str]],
    channel_message_ids: List[int],
    file_id_str: Optional[str] = None,
    pin_code: Optional[str] = None,
    is_one_time: bool = False,
    expires_at: Optional[datetime] = None,
) -> str:
    """
    Yangi fayl yozuvini `stored_files` to'plamiga qo'shadi.

    Parametrlar:
        owner_id: Faylni yuklagan foydalanuvchining Telegram ID raqami.
        telegram_files: `[{"file_id": str, "file_type": str}, ...]` ko'rinishidagi
            ro'yxat (bitta fayl yoki media albom uchun bir nechta element bo'lishi mumkin).
        channel_message_ids: Fayllar saqlangan yopiq kanaldagi xabar ID'lari ro'yxati.
        file_id_str: Havola tokeni. Berilmasa (`None`), avtomatik ravishda
            `generate_file_token()` orqali yaratiladi. Chaqiruvchi tomon
            (masalan, bot handleri) o'z tokenini berishi ham mumkin —
            bu holda MongoDB'dagi unikal indeks tokenning
            takrorlanmasligini kafolatlaydi (takrorlansa `DuplicateKeyError`
            qaytadi, chaqiruvchi yangi token bilan qayta urinishi kerak).
        pin_code: Ixtiyoriy xavfsizlik PIN kodi (kerak bo'lmasa `None`).
        is_one_time: `True` bo'lsa, fayl birinchi marta yuklab olingandan so'ng
            o'z-o'zini yo'q qiladi (self-destruct).
        expires_at: Faylning amal qilish muddati tugaydigan sana/vaqt (TTL uchun).
            `None` bo'lsa, fayl muddatsiz saqlanadi.

    Qaytaradi:
        Yozuvga tegishli noyob token (`file_id_str`).
    """
    if not telegram_files:
        raise ValueError("`telegram_files` ro'yxati bo'sh bo'lishi mumkin emas.")

    collection = get_stored_files_collection()
    token = file_id_str or generate_file_token()

    document = {
        "file_id_str": token,
        "owner_id": owner_id,
        "telegram_files": telegram_files,
        "channel_message_ids": channel_message_ids,
        "pin_code": pin_code,
        "is_one_time": is_one_time,
        "expires_at": expires_at,
        "download_count": 0,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }

    try:
        await collection.insert_one(document)
        logger.info("💾 Yangi fayl yozuvi yaratildi. Token: %s", token)
        return token
    except PyMongoError as exc:
        logger.error("❌ Fayl yozuvini saqlashda xatolik yuz berdi: %s", exc)
        raise


async def get_file_by_token(file_id_str: str) -> Optional[Dict[str, Any]]:
    """
    Berilgan token (`file_id_str`) bo'yicha FAOL fayl yozuvini qidiradi.

    Faqat `is_active: True` bo'lgan yozuvlar qaytariladi — o'chirilgan yoki
    "self-destruct" bo'lib ulgurgan fayllar bu funksiya orqali topilmaydi.

    Qaytaradi:
        Fayl hujjati (dict) yoki topilmasa `None`.
    """
    collection = get_stored_files_collection()
    try:
        document = await collection.find_one(
            {"file_id_str": file_id_str, "is_active": True}
        )
        if document is None:
            logger.info("🔍 Token bo'yicha faol fayl topilmadi: %s", file_id_str)
        return document
    except PyMongoError as exc:
        logger.error("❌ Faylni token bo'yicha qidirishda xatolik yuz berdi: %s", exc)
        raise


async def increment_download(file_id_str: str) -> Optional[Dict[str, Any]]:
    """
    Faylning yuklab olinishlar sonini (`download_count`) bittaga oshiradi.

    Agar fayl `is_one_time=True` bo'lsa, shu yuklashdan so'ng u avtomatik
    ravishda faolsizlantiriladi (`is_active=False`) — ya'ni bir martalik
    fayl "o'z-o'zini yo'q qiladi" (self-destruct).

    Qaytaradi:
        Yangilangan fayl hujjati (dict) yoki fayl topilmasa/faol bo'lmasa `None`.
    """
    collection = get_stored_files_collection()
    try:
        document = await collection.find_one_and_update(
            {"file_id_str": file_id_str, "is_active": True},
            {"$inc": {"download_count": 1}},
            return_document=True,
        )
        if document is None:
            logger.warning(
                "⚠️ Yuklab olishlar sonini oshirib bo'lmadi — fayl topilmadi yoki faol emas: %s",
                file_id_str,
            )
            return None

        logger.info(
            "⬇️ Fayl yuklab olindi. Token: %s, yangi hisob: %s",
            file_id_str,
            document.get("download_count"),
        )

        # Bir martalik fayl bo'lsa — yuklab olingandan so'ng o'zini o'chiradi.
        if document.get("is_one_time"):
            await deactivate_file(file_id_str)
            document["is_active"] = False
            logger.info(
                "💥 Bir martalik fayl yuklab olingandan so'ng faolsizlantirildi: %s",
                file_id_str,
            )

        return document
    except PyMongoError as exc:
        logger.error("❌ Yuklab olishlar sonini oshirishda xatolik yuz berdi: %s", exc)
        raise


async def deactivate_file(file_id_str: str) -> bool:
    """
    Faylni faolsizlantiradi (`is_active=False`) — ya'ni unga kirish yopiladi.
    Fayl hujjati bazadan butunlay o'chirilmaydi, faqat "o'chirilgan" deb belgilanadi.

    Qaytaradi:
        `True` — muvaffaqiyatli faolsizlantirilgan bo'lsa,
        `False` — bunday token topilmagan yoki u allaqachon faolsiz bo'lsa.
    """
    collection = get_stored_files_collection()
    try:
        result = await collection.update_one(
            {"file_id_str": file_id_str, "is_active": True},
            {"$set": {"is_active": False}},
        )
        success = result.modified_count > 0
        if success:
            logger.info("🚫 Fayl faolsizlantirildi: %s", file_id_str)
        else:
            logger.info(
                "ℹ️ Faolsizlantirish uchun fayl topilmadi (yoki allaqachon faolsiz): %s",
                file_id_str,
            )
        return success
    except PyMongoError as exc:
        logger.error("❌ Faylni faolsizlantirishda xatolik yuz berdi: %s", exc)
        raise