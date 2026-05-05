import random
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from transliterate import to_latin
from uzwords import words

GAMES_MENU_TEXT = "🎮 O'yinlardan birini tanlang:"
WORD_ALPHABET_TEXT = "🔤 Qaysi alifboda sizga qulay?"

CYRILLIC_LETTERS = list("абвгдеёжзийклмнопрстуфхцчшъэюяқғҳў")
LATIN_LETTERS = list("abcdefghijklmnopqrstuvxyz") + ["o'", "g'", "sh", "ch"]


def register(bot, main_menu_markup_factory=None, main_state=None):
    game_states = {}

    def edit_or_send(message, text, reply_markup=None, parse_mode=None):
        try:
            bot.edit_message_text(
                text,
                message.chat.id,
                message.message_id,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return message.message_id
        except Exception:
            sent = bot.send_message(
                message.chat.id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return sent.message_id

    def games_menu_markup():
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🧩 So'z topish", callback_data="game:word"),
            InlineKeyboardButton("🔢 Son topish", callback_data="game:number"),
        )
        markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data="game:main"))
        return markup

    def word_alphabet_markup():
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("Lotin", callback_data="game:word:alphabet:latin"),
            InlineKeyboardButton("Krill", callback_data="game:word:alphabet:cyrillic"),
        )
        markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data="game:menu"))
        return markup

    def word_after_win_markup():
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("▶️ Davom et", callback_data="game:word:continue"),
            InlineKeyboardButton("⬅️ Ortga", callback_data="game:menu"),
        )
        return markup

    def number_ranges_markup():
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("1-10", callback_data="game:number:range:1:10"))
        markup.row(
            InlineKeyboardButton("10-50", callback_data="game:number:range:10:50")
        )
        markup.row(
            InlineKeyboardButton("50-100", callback_data="game:number:range:50:100")
        )
        markup.row(InlineKeyboardButton("1-100", callback_data="game:number:range:1:100"))
        markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data="game:menu"))
        return markup

    def number_game_markup():
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🔄 Boshqa son", callback_data="game:number:new"),
            InlineKeyboardButton("⬅️ Ortga", callback_data="game:number"),
        )
        return markup

    def pick_word(alphabet):
        word = random.choice(words)
        while "-" in word or " " in word or len(word) < 3:
            word = random.choice(words)
        return to_latin(word).lower() if alphabet == "latin" else word.lower()

    def word_display(word_state):
        return " ".join(
            letter if letter in word_state["opened"] else "-"
            for letter in word_state["word"]
        )

    def initial_word_letters(word_state):
        alphabet = LATIN_LETTERS if word_state["alphabet"] == "latin" else CYRILLIC_LETTERS
        letters = set(word_state["word"])
        extra_letters = [letter for letter in alphabet if letter not in letters]
        letters.update(
            random.sample(extra_letters, min(len(extra_letters), max(0, 18 - len(letters))))
        )
        return letters

    def build_word_keyboard(word_state):
        letters = word_state.get("letters") or initial_word_letters(word_state)
        word_state["letters"] = letters
        used_letters = set(word_state["used"]) | word_state["opened"]
        buttons = [letter for letter in letters if letter.strip() and letter not in used_letters]
        random.shuffle(buttons)

        markup = InlineKeyboardMarkup(row_width=6)
        rows = [buttons[i:i + 6] for i in range(0, min(len(buttons), 18), 6)]
        for row in rows[:3]:
            markup.row(
                *[
                    InlineKeyboardButton(
                        letter.upper(),
                        callback_data=f"game:word:letter:{letter}",
                    )
                    for letter in row
                ]
            )
        markup.row(
            InlineKeyboardButton("🔁 Boshidan", callback_data="game:word:restart"),
            InlineKeyboardButton("🆘 Yordam", callback_data="game:word:help"),
        )
        markup.row(
            InlineKeyboardButton("🔄 Boshqa so'z", callback_data="game:word:new"),
            InlineKeyboardButton("⬅️ Ortga", callback_data="game:menu"),
        )
        return markup

    def start_word_game(chat_id, message, alphabet):
        word = pick_word(alphabet)
        word_state = {
            "mode": "word",
            "alphabet": alphabet,
            "word": word,
            "opened": set(),
            "used": [],
            "help_used": 0,
            "help_limit": max(1, round(len(word) * 0.4)),
        }
        word_state["letters"] = initial_word_letters(word_state)
        game_states[chat_id] = word_state
        edit_or_send(
            message,
            word_text(game_states[chat_id]),
            build_word_keyboard(game_states[chat_id]),
        )

    def word_text(word_state):
        return (
            "🧩 So'z topish o'yini\n\n"
            f"So'z harflari: {word_display(word_state)}\n"
            "Pastdagi harflardan tanlang."
        )

    def reveal_random_letter(chat_id):
        word_state = game_states[chat_id]
        hidden = [letter for letter in set(word_state["word"]) if letter not in word_state["opened"]]
        if hidden:
            letter = random.choice(hidden)
            word_state["opened"].add(letter)
            if letter not in word_state["used"]:
                word_state["used"].append(letter)
            word_state["help_used"] += 1

    def handle_word_letter(call, letter):
        chat_id = call.message.chat.id
        word_state = game_states.get(chat_id)
        if not word_state or word_state.get("mode") != "word":
            bot.answer_callback_query(call.id)
            return
        if letter in word_state["word"]:
            word_state["opened"].add(letter)
        if letter not in word_state["used"]:
            word_state["used"].append(letter)

        if all(letter in word_state["opened"] for letter in set(word_state["word"])):
            bot.answer_callback_query(call.id, "Topdingiz! 🎉")
            edit_or_send(
                call.message,
                f"🎉 Tabriklayman! Siz so'zni to'liq topdingiz:\n\n✅ {word_state['word'].upper()}",
                word_after_win_markup(),
            )
            return

        bot.answer_callback_query(call.id)
        edit_or_send(call.message, word_text(word_state), build_word_keyboard(word_state))

    def start_number_game(chat_id, message, low, high):
        target = random.randint(low, high)
        game_states[chat_id] = {
            "mode": "number",
            "low": low,
            "high": high,
            "current_low": low,
            "current_high": high,
            "target": target,
            "last_bot_message_id": message.message_id,
        }
        text = (
            f"🔢 Men {low}-{high} orasida son o'yladim, topa olarmikansiz?\n\n"
            "Taxminingizni xabar qilib yuboring."
        )
        game_states[chat_id]["last_bot_message_id"] = edit_or_send(
            message,
            text,
            number_game_markup(),
        )

    def number_prompt(number_state, hint=None):
        hint_text = f"{hint}\n\n" if hint else ""
        return (
            f"{hint_text}"
            f"{number_state['current_low']}-{number_state['current_high']} orasida son kiriting."
        )

    def show_main(message):
        if main_state is not None:
            main_state[message.chat.id] = "main"
        if main_menu_markup_factory:
            edit_or_send(message, "💼 Bot xizmatlaridan birini tanlang:", main_menu_markup_factory())
        else:
            edit_or_send(message, GAMES_MENU_TEXT, games_menu_markup())

    @bot.callback_query_handler(func=lambda call: call.data.startswith("game:"))
    def handle_game_callbacks(call):
        chat_id = call.message.chat.id
        data = call.data.split(":")
        if not (call.data.startswith("game:word:letter:") or call.data == "game:word:help"):
            bot.answer_callback_query(call.id)

        if call.data == "game:open" or call.data == "game:menu":
            if main_state is not None:
                main_state[chat_id] = "games"
            game_states.pop(chat_id, None)
            edit_or_send(call.message, GAMES_MENU_TEXT, games_menu_markup())
            return
        if call.data == "game:main":
            game_states.pop(chat_id, None)
            show_main(call.message)
            return
        if call.data == "game:word":
            if main_state is not None:
                main_state[chat_id] = "games_word_alphabet"
            edit_or_send(call.message, WORD_ALPHABET_TEXT, word_alphabet_markup())
            return
        if call.data.startswith("game:word:alphabet:"):
            if main_state is not None:
                main_state[chat_id] = "game_word"
            start_word_game(chat_id, call.message, data[-1])
            return
        if call.data in ["game:word:new", "game:word:continue"]:
            word_state = game_states.get(chat_id, {})
            start_word_game(chat_id, call.message, word_state.get("alphabet", "latin"))
            return
        if call.data == "game:word:restart":
            word_state = game_states.get(chat_id)
            if word_state:
                word_state["opened"] = set()
                word_state["used"] = []
                word_state["help_used"] = 0
                edit_or_send(call.message, word_text(word_state), build_word_keyboard(word_state))
            return
        if call.data == "game:word:help":
            word_state = game_states.get(chat_id)
            if not word_state:
                bot.answer_callback_query(call.id)
                return
            if word_state["help_used"] >= word_state["help_limit"]:
                bot.answer_callback_query(
                    call.id,
                    "Bu imkoniyatingiz bu so'zda tugadi.",
                    show_alert=True,
                )
                return
            bot.answer_callback_query(call.id)
            reveal_random_letter(chat_id)
            if all(letter in word_state["opened"] for letter in set(word_state["word"])):
                edit_or_send(
                    call.message,
                    f"🎉 Tabriklayman! Siz so'zni to'liq topdingiz:\n\n✅ {word_state['word'].upper()}",
                    word_after_win_markup(),
                )
            else:
                edit_or_send(call.message, word_text(word_state), build_word_keyboard(word_state))
            return
        if call.data.startswith("game:word:letter:"):
            handle_word_letter(call, call.data.split(":", 3)[3])
            return
        if call.data == "game:number":
            if main_state is not None:
                main_state[chat_id] = "games_number_range"
            game_states.pop(chat_id, None)
            edit_or_send(call.message, "🔢 Oraliq tanlang:", number_ranges_markup())
            return
        if call.data.startswith("game:number:range:"):
            if main_state is not None:
                main_state[chat_id] = "game_number"
            low, high = int(data[-2]), int(data[-1])
            start_number_game(chat_id, call.message, low, high)
            return
        if call.data == "game:number:new":
            number_state = game_states.get(chat_id)
            if number_state:
                start_number_game(chat_id, call.message, number_state["low"], number_state["high"])
            return

    def process_text(message):
        chat_id = message.chat.id
        number_state = game_states.get(chat_id)
        if not number_state or number_state.get("mode") != "number":
            return False

        try:
            guess = int(message.text.strip())
        except ValueError:
            bot.send_message(chat_id, "Iltimos, matn emas son kiriting.", reply_markup=number_game_markup())
            return True

        try:
            bot.delete_message(chat_id, number_state.get("last_bot_message_id"))
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        if guess < number_state["current_low"] or guess > number_state["current_high"]:
            sent = bot.send_message(
                chat_id,
                f"Iltimos! e'tiborli bo'ling, son {number_state['current_low']}-{number_state['current_high']} orasida.",
                reply_markup=number_game_markup(),
            )
            number_state["last_bot_message_id"] = sent.message_id
            return True

        if guess == number_state["target"]:
            sent = bot.send_message(
                chat_id,
                f"🎉 Tabriklayman! Siz {number_state['target']} sonini topdingiz!",
                reply_markup=number_game_markup(),
            )
            number_state["last_bot_message_id"] = sent.message_id
            return True

        if guess < number_state["target"]:
            number_state["current_low"] = max(number_state["current_low"], guess)
            hint = "Son siz taxmin qilgan sondan katta edi."
        else:
            number_state["current_high"] = min(number_state["current_high"], guess)
            hint = "Son siz taxmin qilgan sondan kichik edi."

        sent = bot.send_message(
            chat_id,
            number_prompt(number_state, hint),
            reply_markup=number_game_markup(),
        )
        number_state["last_bot_message_id"] = sent.message_id
        return True

    return {
        "games_menu_markup": games_menu_markup,
        "process_text": process_text,
    }