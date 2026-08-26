import asyncio
import html
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
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

MSK = ZoneInfo("Europe/Moscow")
WARNING_DAYS_LEFT = 2  # за сколько дней до истечения слать предупреждение

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

    # Учёт домов: либо ссылка на существующий аккаунт (account_id),
    # либо самостоятельная запись с логином/паролем (login/password).
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS houses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            account_id INTEGER,
            server_number INTEGER NOT NULL,
            login TEXT,
            password TEXT,
            owner_name TEXT,
            days_paid INTEGER NOT NULL,
            added_at TEXT NOT NULL
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_houses_chat_server "
        "ON houses (chat_id, server_number)"
    )

    # Хранит id закреплённого сообщения-сводки по домам для каждого чата
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS house_config (
            chat_id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL
        )
        """
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
# УЧЁТ ДОМОВ
# ─────────────────────────────────────────────────────────────
async def upsert_house(chat_id, account_id, server_number, login, password, owner_name, days_paid):
    now_iso = datetime.now(MSK).isoformat()

    existing_id = None
    if account_id is not None:
        cur = await db.execute(
            "SELECT id FROM houses WHERE chat_id = ? AND account_id = ?",
            (chat_id, account_id),
        )
        row = await cur.fetchone()
        if row:
            existing_id = row["id"]
    elif login is not None:
        # Fernet-шифрование не детерминировано, поэтому сравниваем расшифрованные значения
        cur = await db.execute(
            "SELECT id, login FROM houses WHERE chat_id = ? AND server_number = ? "
            "AND account_id IS NULL AND login IS NOT NULL",
            (chat_id, server_number),
        )
        rows = await cur.fetchall()
        for r in rows:
            if decrypt(r["login"]) == login:
                existing_id = r["id"]
                break

    if existing_id:
        await db.execute(
            "UPDATE houses SET owner_name = ?, days_paid = ?, added_at = ? WHERE id = ?",
            (owner_name, days_paid, now_iso, existing_id),
        )
        await db.commit()
        return existing_id, True  # обновили (продлили оплату)

    enc_login = encrypt(login) if login is not None else None
    enc_password = encrypt(password) if password is not None else None
    cur = await db.execute(
        """
        INSERT INTO houses (chat_id, account_id, server_number, login, password, owner_name, days_paid, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (chat_id, account_id, server_number, enc_login, enc_password, owner_name, days_paid, now_iso),
    )
    await db.commit()
    return cur.lastrowid, False  # создали новую запись


async def get_houses(chat_id: int):
    cur = await db.execute(
        """
        SELECT id, account_id, server_number, login, password, owner_name, days_paid, added_at
        FROM houses
        WHERE chat_id = ?
        ORDER BY server_number, id
        """,
        (chat_id,),
    )
    return await cur.fetchall()


async def get_linked_account_ids(chat_id: int):
    cur = await db.execute(
        "SELECT account_id FROM houses WHERE chat_id = ? AND account_id IS NOT NULL",
        (chat_id,),
    )
    rows = await cur.fetchall()
    return {r["account_id"] for r in rows}


async def get_house_message_id(chat_id: int):
    cur = await db.execute(
        "SELECT message_id FROM house_config WHERE chat_id = ?", (chat_id,)
    )
    row = await cur.fetchone()
    return row["message_id"] if row else None


async def set_house_message_id(chat_id: int, message_id: int):
    await db.execute(
        "INSERT INTO house_config (chat_id, message_id) VALUES (?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET message_id = excluded.message_id",
        (chat_id, message_id),
    )
    await db.commit()


async def delete_house(chat_id: int, house_id: int) -> bool:
    cur = await db.execute(
        "DELETE FROM houses WHERE id = ? AND chat_id = ?", (house_id, chat_id)
    )
    await db.commit()
    return cur.rowcount > 0


async def edit_house_days(chat_id: int, house_id: int, new_days: int) -> bool:
    """Продлевает/меняет оплату дома по его уникальному номеру, сбрасывая
    точку отсчёта на текущий момент (МСК)."""
    now_iso = datetime.now(MSK).isoformat()
    cur = await db.execute(
        "UPDATE houses SET days_paid = ?, added_at = ? WHERE id = ? AND chat_id = ?",
        (new_days, now_iso, house_id, chat_id),
    )
    await db.commit()
    return cur.rowcount > 0


async def get_house_by_id(chat_id: int, house_id: int):
    cur = await db.execute(
        "SELECT id, account_id, server_number, login, password, owner_name, days_paid, added_at "
        "FROM houses WHERE id = ? AND chat_id = ?",
        (house_id, chat_id),
    )
    return await cur.fetchone()


def compute_days_left(added_at_iso: str, days_paid: int) -> int:
    added = datetime.fromisoformat(added_at_iso)
    if added.tzinfo is None:
        added = added.replace(tzinfo=MSK)
    added_date = added.astimezone(MSK).date()
    today_date = datetime.now(MSK).date()
    elapsed_days = (today_date - added_date).days
    return days_paid - elapsed_days


async def build_house_message_text(chat_id: int) -> str:
    houses = await get_houses(chat_id)
    if not houses:
        return "🏠 <b>Учёт домов</b>\n\nПока пусто. Добавь запись через /house."

    lines = ["🏠 <b>Учёт домов</b>"]
    current_server = None

    for h in houses:
        if h["server_number"] != current_server:
            current_server = h["server_number"]
            server_name = SERVERS.get(current_server, "Неизвестный сервер")
            lines.append(f"\n<b>{html.escape(server_name)} #{current_server}</b>")

        days_left = compute_days_left(h["added_at"], h["days_paid"])
        if days_left < 0:
            status = f"⛔ просрочено на {abs(days_left)} дн."
        elif days_left <= 3:
            status = f"⚠️ осталось {days_left} дн."
        else:
            status = f"осталось {days_left} дн."

        if h["account_id"] is not None:
            label = f"🏠№{h['id']} (аккаунт №{h['account_id']})"
            if h["owner_name"]:
                label += f" | Владелец: {html.escape(h['owner_name'])}"
        else:
            login_plain = html.escape(decrypt(h["login"])) if h["login"] else "—"
            password_plain = html.escape(decrypt(h["password"])) if h["password"] else "—"
            label = f"🏠№{h['id']} | <code>{login_plain}</code> / <code>{password_plain}</code>"

        lines.append(f"• {label} | {status}")

    return "\n".join(lines)


async def refresh_house_message(bot: Bot, chat_id: int):
    text = await build_house_message_text(chat_id)
    message_id = await get_house_message_id(chat_id)

    if message_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            # сообщение удалено/недоступно — отправим новое ниже
            logging.info(f"Не удалось отредактировать сообщение домов: {e}")

    sent = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    await set_house_message_id(chat_id, sent.message_id)


async def get_house_chat_ids():
    cur = await db.execute("SELECT DISTINCT chat_id FROM houses")
    rows = await cur.fetchall()
    return [r["chat_id"] for r in rows]


async def run_daily_house_update(bot: Bot):
    """Обновляет сводные сообщения и шлёт предупреждения об истекающей оплате.
    Вызывается автоматически каждый день в 00:00 по МСК."""
    for chat_id in await get_house_chat_ids():
        await refresh_house_message(bot, chat_id)

        for h in await get_houses(chat_id):
            days_left = compute_days_left(h["added_at"], h["days_paid"])
            if days_left != WARNING_DAYS_LEFT:
                continue

            server_name = SERVERS.get(h["server_number"], "Неизвестный сервер")
            if h["account_id"] is not None:
                detail = f"аккаунт №{h['account_id']}"
                if h["owner_name"]:
                    detail += f", владелец {html.escape(h['owner_name'])}"
            else:
                login_plain = html.escape(decrypt(h["login"])) if h["login"] else "—"
                detail = f"логин <code>{login_plain}</code>"

            warning_text = (
                f"⚠️ <b>Скоро истекает оплата дома!</b>\n"
                f"🏠№{h['id']} | {server_name} #{h['server_number']}\n"
                f"{detail}\n"
                f"Осталось: {days_left} дн. Продли через /house."
            )
            try:
                await bot.send_message(chat_id, warning_text, parse_mode="HTML")
            except Exception as e:
                logging.warning(f"Не удалось отправить предупреждение по дому №{h['id']}: {e}")


async def house_daily_scheduler(bot: Bot):
    """Фоновый цикл: спит до ближайшей полуночи по МСК, затем запускает
    ежедневное обновление домов, и так постоянно."""
    while True:
        now = datetime.now(MSK)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        sleep_seconds = (next_midnight - now).total_seconds()
        await asyncio.sleep(max(sleep_seconds, 1))
        try:
            await run_daily_house_update(bot)
        except Exception as e:
            logging.exception(f"Ошибка в ежедневном обновлении домов: {e}")


# ─────────────────────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(get_help_text())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(get_help_text())


def get_help_text() -> str:
    return (
        "Привет! Я бот для хранения игровых аккаунтов по серверам.\n\n"
        "<b>Аккаунты</b>\n"
        "/addacc СерверИлиНомер логин пароль — добавить аккаунт\n"
        "/list или /panel — показать все 91 сервер\n"
        "/accedit номер логин пароль — изменить логин и пароль аккаунта\n"
        "/accdel номер_аккаунта — удалить аккаунт (с подтверждением)\n"
        "/search СерверИлиНомер — найти все аккаунты на сервере (кроме учтённых в домах)\n\n"
        "<b>Учёт домов</b>\n"
        "/house номер_аккаунта дни имя_владельца — привязать дом к существующему аккаунту\n"
        "/house СерверИлиНомер логин пароль дни — добавить дом с отдельным логином/паролем\n"
        "/hedit номер_дома дни — изменить/продлить оплату по номеру дома (если уже оплатили)\n"
        "/hdel номер_дома — удалить запись о доме (с подтверждением)\n"
        "Повторный вызов /house с тем же аккаунтом или логином продлевает оплату (сбрасывает счётчик дней).\n"
        "Дни автоматически списываются каждый день ровно в 00:00 по МСК, сводное сообщение обновляется само.\n"
        f"За {WARNING_DAYS_LEFT} дня до истечения бот сам пришлёт предупреждение в этот чат.\n"
        "Бот сам ведёт и обновляет одно сводное сообщение по всем домам — просто закрепи его в группе после первого добавления."
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


@router.message(Command("house"))
async def cmd_house(message: Message):
    args = message.text.split()[1:]

    usage = (
        "Используй один из форматов:\n"
        "/house номер_аккаунта дни имя_владельца\n"
        "/house СерверИлиНомер логин пароль дни\n\n"
        "Повторный вызов с тем же аккаунтом/логином продлевает оплату."
    )

    if len(args) == 3:
        # Режим 1: привязка к существующему аккаунту
        acc_id_raw, days_raw, owner_name = args
        if not acc_id_raw.isdigit() or not days_raw.isdigit():
            await message.answer(usage)
            return

        acc_id, days = int(acc_id_raw), int(days_raw)
        account = await get_account_by_id(message.chat.id, acc_id)
        if not account:
            await message.answer("Аккаунт с таким номером не найден в этой группе.")
            return

        house_id, renewed = await upsert_house(
            chat_id=message.chat.id,
            account_id=acc_id,
            server_number=account["server_number"],
            login=None,
            password=None,
            owner_name=owner_name,
            days_paid=days,
        )

    elif len(args) == 4:
        # Режим 2: отдельная запись с логином и паролем
        server_raw, login, password, days_raw = args
        if not days_raw.isdigit():
            await message.answer(usage)
            return

        resolved = resolve_server(server_raw)
        if not resolved:
            await message.answer(f"Не нашёл сервер «{server_raw}». Проверь название или номер.")
            return

        server_number, _ = resolved
        days = int(days_raw)

        house_id, renewed = await upsert_house(
            chat_id=message.chat.id,
            account_id=None,
            server_number=server_number,
            login=login,
            password=password,
            owner_name=None,
            days_paid=days,
        )

    else:
        await message.answer(usage)
        return

    await refresh_house_message(message.bot, message.chat.id)

    action = "Оплата продлена" if renewed else "Дом добавлен в учёт"
    await message.answer(f"🏠 {action} (запись №{house_id}), сводка обновлена выше.")


@router.message(Command("hedit"))
async def cmd_hedit(message: Message):
    args = message.text.split()[1:]

    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await message.answer(
            "Используй: /hedit номер_дома новые_дни\n"
            "Например: /hedit 5 30 — продлить дом №5 на 30 дней от сегодня."
        )
        return

    house_id, new_days = int(args[0]), int(args[1])
    existing = await get_house_by_id(message.chat.id, house_id)

    if not existing:
        await message.answer("Запись с таким номером не найдена в учёте домов.")
        return

    await edit_house_days(message.chat.id, house_id, new_days)
    await refresh_house_message(message.bot, message.chat.id)

    await message.answer(f"✏️ Дом №{house_id}: оплата обновлена, осталось {new_days} дн. Сводка обновлена выше.")


@router.message(Command("hdel"))
async def cmd_hdel(message: Message):
    args = message.text.split(maxsplit=1)[1:]

    if not args or not args[0].strip().isdigit():
        await message.answer("Используй: /hdel номер_дома\nНапример: /hdel 5")
        return

    house_id = int(args[0].strip())
    existing = await get_house_by_id(message.chat.id, house_id)

    if not existing:
        await message.answer("Запись с таким номером не найдена в учёте домов.")
        return

    server_name = SERVERS.get(existing["server_number"], "Неизвестный сервер")
    if existing["account_id"] is not None:
        detail = f"аккаунт №{existing['account_id']}"
        if existing["owner_name"]:
            detail += f", владелец {existing['owner_name']}"
    else:
        detail = f"логин {decrypt(existing['login'])}" if existing["login"] else "без логина"

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"housedelconfirm:{house_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="housedelcancel"),
        ]]
    )

    await message.answer(
        f"⚠️ Точно удалить запись о доме №{house_id}?\n"
        f"Сервер: {server_name}\n"
        f"{detail}\n\n"
        f"Это действие необратимо.",
        reply_markup=confirm_kb,
    )

@router.callback_query(F.data.startswith("housedelconfirm:"))
async def confirm_house_delete(callback: CallbackQuery):
    house_id = int(callback.data.split(":")[1])
    ok = await delete_house(callback.message.chat.id, house_id)

    if ok:
        await callback.message.edit_text(f"🗑 Запись о доме №{house_id} удалена.")
        await refresh_house_message(callback.bot, callback.message.chat.id)
    else:
        await callback.message.edit_text("Запись уже удалена или не найдена.")
    await callback.answer()


@router.callback_query(F.data == "housedelcancel")
async def cancel_house_delete(callback: CallbackQuery):
    await callback.message.edit_text("Удаление отменено.")
    await callback.answer()


@router.message(Command("search"))
async def cmd_search(message: Message):
    args = message.text.split(maxsplit=1)[1:]

    if not args:
        await message.answer("Используй: /search СерверИлиНомер\nНапример: /search Тюмень")
        return

    resolved = resolve_server(args[0])
    if not resolved:
        await message.answer(f"Не нашёл сервер «{args[0]}». Проверь название или номер.")
        return

    server_number, server_name = resolved
    accounts = await get_accounts_for_server(message.chat.id, server_number)
    linked_ids = await get_linked_account_ids(message.chat.id)
    filtered = [acc for acc in accounts if acc["id"] not in linked_ids]

    if not filtered:
        await message.answer(
            f"На сервере {server_name} #{server_number} нет свободных аккаунтов "
            f"(либо их нет вовсе, либо все уже учтены как дома)."
        )
        return

    text_lines = [f"<b>🔍 Аккаунты на {server_name} #{server_number}:</b>\n"]
    for acc in filtered:
        login = html.escape(decrypt(acc["login"]))
        password = html.escape(decrypt(acc["password"]))
        text_lines.append(
            f"№{acc['id']} | Логин: <code>{login}</code> | Пароль: <code>{password}</code>"
        )

    await message.answer("\n".join(text_lines), parse_mode="HTML")


# ─────────────────────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────────────────────
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(house_daily_scheduler(bot))
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
