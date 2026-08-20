import asyncio
import html
import logging
import time
from pathlib import Path
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
import os

# ─────────────────────────────────────────────────────────────
# НАСТРОЙКИ (берутся из .env — см. .env.example)
# ─────────────────────────────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")
DB_PATH = Path(__file__).parent / "accounts.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Заполни файл .env (см. .env.example).")

if not ENCRYPTION_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY не найден. Сгенерируй его командой:\n"
        "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
        "и вставь результат в .env как ENCRYPTION_KEY=..."
    )

if not ADMIN_GROUP_ID:
    raise RuntimeError(
        "ADMIN_GROUP_ID не найден. Узнай ID своей группы (см. README.md) "
        "и вставь его в .env как ADMIN_GROUP_ID=-100xxxxxxxxxx"
    )

ADMIN_GROUP_ID = int(ADMIN_GROUP_ID)

fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return "⚠️ не удалось расшифровать (неверный ключ)"


logging.basicConfig(level=logging.INFO)
router = Router()

router.message.filter(F.chat.id == ADMIN_GROUP_ID)
router.callback_query.filter(F.message.chat.id == ADMIN_GROUP_ID)

# ─────────────────────────────────────────────────────────────
# СПРАВОЧНИК СЕРВЕРОВ (номер -> название)
# ─────────────────────────────────────────────────────────────
SERVERS = {
    1: "Ред", 2: "Грин", 3: "Блю", 4: "Йеллоу", 5: "Оранж",
    6: "Пурпл", 7: "Лайм", 8: "Пинк", 9: "Черри", 10: "Блэк",
    11: "Индиго", 12: "Уайт", 13: "Маджента", 14: "Кримсон", 15: "Голд",
    16: "Азур", 17: "Платинум", 18: "Аква", 19: "Грей", 20: "Айс",
    21: "Чилли", 22: "Чоко", 23: "Москва", 24: "Спб", 25: "Уфа",
    26: "Сочи", 27: "Казань", 28: "Самара", 29: "Ростов", 30: "Анапа",
    31: "Екб", 32: "Краснодар", 33: "Арзамас", 34: "Новосибирск", 35: "Грозный",
    36: "Саратов", 37: "Омск", 38: "Иркутск", 39: "Волгоград", 40: "Воронеж",
    41: "Белгород", 42: "Махачкала", 43: "Владикавказ", 44: "Владивосток", 45: "Калининград",
    46: "Челябинск", 47: "Красноярск", 48: "Чебоксары", 49: "Хабаровск", 50: "Пермь",
    51: "Тула", 52: "Рязань", 53: "Мурманск", 54: "Пенза", 55: "Курск",
    56: "Архангельск", 57: "Оренбург", 58: "Киров", 59: "Кемерово", 60: "Тюмень",
    61: "Тольятти", 62: "Иваново", 63: "Ставрополь", 64: "Смоленск", 65: "Псков",
    66: "Брянск", 67: "Орёл", 68: "Ярославль", 69: "Барнаул", 70: "Липецк",
    71: "Ульяновск", 72: "Якутск", 73: "Тамбов", 74: "Братск", 75: "Астрахань",
    76: "Чита", 77: "Кострома", 78: "Владимир", 79: "Калуга", 80: "Новгород",
    81: "Таганрог", 82: "Вологда", 83: "Тверь", 84: "Томск", 85: "Ижевск",
    86: "Сургут", 87: "Подольск", 88: "Магадан", 89: "Череповец", 90: "Норильск",
    91: "Астана",
}

_NAME_TO_NUMBER = {name.strip().lower(): number for number, name in SERVERS.items()}


def resolve_server(identifier: str):
    identifier = identifier.strip()

    if identifier.isdigit():
        number = int(identifier)
        name = SERVERS.get(number)
        if name:
            return number, name
        return None

    number = _NAME_TO_NUMBER.get(identifier.lower())
    if number:
        return number, SERVERS[number]

    return None

# ─────────────────────────────────────────────────────────────
# КЛАВИАТУРА СПИСКА СЕРВЕРОВ — постраничная, по 15 серверов на страницу
# ─────────────────────────────────────────────────────────────
SERVERS_PER_PAGE = 15
_SORTED_SERVERS = sorted(SERVERS.items())
TOTAL_PAGES = (len(_SORTED_SERVERS) - 1) // SERVERS_PER_PAGE + 1


def build_server_page_keyboard(page: int) -> InlineKeyboardMarkup:
    page = max(0, min(page, TOTAL_PAGES - 1))
    start = page * SERVERS_PER_PAGE
    end = start + SERVERS_PER_PAGE
    page_servers = _SORTED_SERVERS[start:end]

    buttons = [
        InlineKeyboardButton(text=f"{name} #{number}", callback_data=f"server:{number}:{page}")
        for number, name in page_servers
    ]
    rows = [buttons[i: i + 2] for i in range(0, len(buttons), 2)]

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"page:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{TOTAL_PAGES}", callback_data="noop"))
    if page < TOTAL_PAGES - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"page:{page + 1}"))
    rows.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)

# ─────────────────────────────────────────────────────────────
# БАЗА ДАННЫХ (полностью асинхронная, через aiosqlite)
#
# Держим ОДНО общее соединение на всё время жизни бота вместо
# open/close на каждый запрос — это и быстрее, и не блокирует
# event loop синхронным I/O, как было раньше с sqlite3.
# ─────────────────────────────────────────────────────────────
db: Optional[aiosqlite.Connection] = None


async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row

    # WAL заметно снижает блокировки при параллельных чтениях/записях
    await db.execute("PRAGMA journal_mode=WAL")

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            server_number INTEGER NOT NULL,
            login TEXT NOT NULL,
            password TEXT NOT NULL
        )
        """
    )
    # Индекс под самый частый запрос: WHERE owner_id = ? AND server_number = ?
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_accounts_owner_server "
        "ON accounts (owner_id, server_number)"
    )
    await db.commit()


async def add_account(chat_id: int, server_number: int, login: str, password: str) -> int:
    cur = await db.execute(
        "INSERT INTO accounts (owner_id, server_number, login, password) VALUES (?, ?, ?, ?)",
        (chat_id, server_number, encrypt(login), encrypt(password)),
    )
    await db.commit()
    return cur.lastrowid


async def update_account(chat_id: int, acc_id: int, login: str, password: str) -> bool:
    cur = await db.execute(
        "UPDATE accounts SET login = ?, password = ? WHERE id = ? AND owner_id = ?",
        (encrypt(login), encrypt(password), acc_id, chat_id),
    )
    await db.commit()
    return cur.rowcount > 0


async def get_account_by_id(chat_id: int, acc_id: int):
    cur = await db.execute(
        "SELECT id, server_number, login, password FROM accounts WHERE id = ? AND owner_id = ?",
        (acc_id, chat_id),
    )
    return await cur.fetchone()


async def delete_account(chat_id: int, acc_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM accounts WHERE id = ? AND owner_id = ?", (acc_id, chat_id)
    )
    await db.commit()
    return cur.rowcount > 0


async def get_accounts_for_server(chat_id: int, server_number: int):
    cur = await db.execute(
        """
        SELECT id, server_number, login, password
        FROM accounts
        WHERE owner_id = ? AND server_number = ?
        ORDER BY id
        """,
        (chat_id, server_number),
    )
    rows = await cur.fetchall()
    return rows


# ─────────────────────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я бот для хранения игровых аккаунтов по серверам.\n\n"
        "Команды:\n"
        "/addacc СерверИлиНомер логин пароль — добавить аккаунт (сервер можно писать названием или номером, регистр не важен)\n"
        "/list или /panel — показать все 91 сервер\n"
        "/accedit номер логин пароль — изменить логин и пароль аккаунта\n"
        "/accdel номер_аккаунта — удалить аккаунт по его уникальному номеру (с подтверждением)"
    )


@router.message(Command("addacc"))
async def cmd_addacc(message: Message):
    args = message.text.split(maxsplit=3)[1:]

    if len(args) < 3:
        await message.answer(
            "Неверный формат.\n"
            "Используй: /addacc СерверИлиНомер логин пароль\n"
            "Например: /addacc Астана Lite_Rework MyPass123\n"
            "Или: /addacc 91 Lite_Rework MyPass123"
        )
        return

    server_raw, login, password = args
    resolved = resolve_server(server_raw)

    if not resolved:
        await message.answer(
            f"Не нашёл сервер «{server_raw}». Проверь название или номер (1–91) и попробуй ещё раз."
        )
        return

    server_number, server_name = resolved

    acc_id = await add_account(
        chat_id=message.chat.id,
        server_number=server_number,
        login=login,
        password=password,
    )

    await message.answer(
        f"✅ Аккаунт добавлен ({message.from_user.full_name}).\n"
        f"Сервер: {server_name} #{server_number}\n"
        f"Логин: {login}\n"
        f"Уникальный номер аккаунта: {acc_id}"
    )


@router.message(Command("accedit"))
async def cmd_accedit(message: Message):
    args = message.text.split(maxsplit=3)[1:]

    if len(args) < 3 or not args[0].strip().isdigit():
        await message.answer(
            "Неверный формат.\n"
            "Используй: /accedit номер_аккаунта новый_логин новый_пароль\n"
            "Например: /accedit 3 Lite_Rework NewPass456"
        )
        return

    acc_id = int(args[0].strip())
    new_login, new_password = args[1], args[2]

    existing = await get_account_by_id(message.chat.id, acc_id)
    if not existing:
        await message.answer("Аккаунт с таким номером не найден в этой группе.")
        return

    await update_account(message.chat.id, acc_id, new_login, new_password)

    server_name = SERVERS.get(existing["server_number"], "Неизвестный сервер")
    await message.answer(
        f"✏️ Аккаунт №{acc_id} обновлён ({message.from_user.full_name}).\n"
        f"Сервер: {server_name} #{existing['server_number']}\n"
        f"Новый логин: {new_login}"
    )


@router.message(Command("accdel"))
async def cmd_accdel(message: Message):
    args = message.text.split(maxsplit=1)[1:]

    if not args or not args[0].strip().isdigit():
        await message.answer("Используй: /accdel номер_аккаунта\nНапример: /accdel 3")
        return

    acc_id = int(args[0].strip())
    existing = await get_account_by_id(message.chat.id, acc_id)

    if not existing:
        await message.answer("Аккаунт с таким номером не найден в этой группе.")
        return

    server_name = SERVERS.get(existing["server_number"], "Неизвестный сервер")
    login = decrypt(existing["login"])

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delconfirm:{acc_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="delcancel"),
        ]]
    )

    await message.answer(
        f"⚠️ Точно удалить аккаунт №{acc_id}?\n"
        f"Сервер: {server_name}\n"
        f"Логин: {login}\n\n"
        f"Это действие необратимо.",
        reply_markup=confirm_kb,
    )


@router.callback_query(F.data.startswith("delconfirm:"))
async def confirm_delete(callback: CallbackQuery):
    acc_id = int(callback.data.split(":")[1])
    ok = await delete_account(callback.message.chat.id, acc_id)

    if ok:
        await callback.message.edit_text(f"🗑 Аккаунт №{acc_id} удалён.")
    else:
        await callback.message.edit_text("Аккаунт уже удалён или не найден.")
    await callback.answer()


@router.callback_query(F.data == "delcancel")
async def cancel_delete(callback: CallbackQuery):
    await callback.message.edit_text("Удаление отменено.")
    await callback.answer()


@router.message(Command("list"))
@router.message(Command("panel"))
async def cmd_list(message: Message):
    await message.answer("Выбери сервер:", reply_markup=build_server_page_keyboard(0))


@router.callback_query(F.data.startswith("page:"))
async def paginate_servers(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=build_server_page_keyboard(page))
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


# ─────────────────────────────────────────────────────────────
# CALLBACK: показ аккаунтов выбранного сервера
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("server:"))
async def show_server_accounts(callback: CallbackQuery):
    t0 = time.perf_counter()
    parts = callback.data.split(":")
    server_number = int(parts[1])
    server_name = SERVERS.get(server_number, "Неизвестный сервер")

    t1 = time.perf_counter()
    accounts = await get_accounts_for_server(callback.message.chat.id, server_number)
    t2 = time.perf_counter()
    logging.info(
        f"[TIMING] server={server_number} parse={t1-t0:.3f}s db={t2-t1:.3f}s"
    )

    if not accounts:
        await callback.answer(
            f"На сервере {server_name} #{server_number} пока нет сохранённых аккаунтов.",
            show_alert=True,
        )
        return

    text_lines = [f"<b>Аккаунты на {server_name} #{server_number}:</b>\n"]
    for acc in accounts:
        login = html.escape(decrypt(acc['login']))
        password = html.escape(decrypt(acc['password']))
        text_lines.append(
            f"№{acc['id']} | Логин: <code>{login}</code> | Пароль: <code>{password}</code>"
        )
    t3 = time.perf_counter()

    await callback.message.answer("\n".join(text_lines), parse_mode="HTML")
    t4 = time.perf_counter()
    await callback.answer()
    t5 = time.perf_counter()
    logging.info(
        f"[TIMING] decrypt={t3-t2:.3f}s send={t4-t3:.3f}s answer={t5-t4:.3f}s TOTAL={t5-t0:.3f}s"
    )


# ─────────────────────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────────────────────
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
