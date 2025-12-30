import asyncio
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"  # Вставь свой токен
ADMIN_ID = 6893832048  # Вставь свой Telegram ID
# ===================================================

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Хранилище данных
DATA_FILE = "bot_data.json"
FILES_DIR = "user_files"

# Создаём папку для файлов
os.makedirs(FILES_DIR, exist_ok=True)

# Глобальные переменные
data = {
    "files": {},  # {file_id: {"name": "...", "path": "...", "count": N, "uploaded": "date"}}
    "delay_seconds": 60,  # Задержка по умолчанию
    "channel_id": None,
    "is_running": False,
    "current_file": None,
    "current_index": 0
}

# Флаг для остановки рассылки
stop_flag = False


class States(StatesGroup):
    waiting_file = State()
    waiting_delay = State()
    waiting_channel = State()
    waiting_file_name = State()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_data():
    global data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data.update(json.load(f))


load_data()


# ==================== КЛАВИАТУРЫ ====================

def main_menu_kb():
    buttons = [
        [InlineKeyboardButton(text="📁 Мои файлы", callback_data="my_files")],
        [InlineKeyboardButton(text="📤 Загрузить файл", callback_data="upload_file")],
        [InlineKeyboardButton(text="⏱ Настройка задержки", callback_data="set_delay")],
        [InlineKeyboardButton(text="📢 Настройка канала", callback_data="set_channel")],
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="start_sending")],
        [InlineKeyboardButton(text="🛑 Остановить рассылку", callback_data="stop_sending")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def files_list_kb():
    buttons = []
    for file_id, file_info in data["files"].items():
        status = "✅" if data["current_file"] == file_id else ""
        btn_text = f"{status} {file_info['name']} ({file_info['count']} юзеров)"
        buttons.append([InlineKeyboardButton(
            text=btn_text, 
            callback_data=f"select_file:{file_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def file_actions_kb(file_id):
    buttons = [
        [InlineKeyboardButton(text="✅ Выбрать для рассылки", callback_data=f"choose_file:{file_id}")],
        [InlineKeyboardButton(text="👀 Просмотреть", callback_data=f"view_file:{file_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_file:{file_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="my_files")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delay_kb():
    buttons = [
        [
            InlineKeyboardButton(text="10 сек", callback_data="delay:10"),
            InlineKeyboardButton(text="30 сек", callback_data="delay:30"),
            InlineKeyboardButton(text="60 сек", callback_data="delay:60")
        ],
        [
            InlineKeyboardButton(text="2 мин", callback_data="delay:120"),
            InlineKeyboardButton(text="5 мин", callback_data="delay:300"),
            InlineKeyboardButton(text="10 мин", callback_data="delay:600")
        ],
        [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="delay_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_delete_kb(file_id):
    buttons = [
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete:{file_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"select_file:{file_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])


def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_main")]
    ])


# ==================== ОБРАБОТЧИКИ ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён!")
        return
    
    await message.answer(
        "👋 Привет! Я бот для рассылки username в канал.\n\n"
        "📌 Что я умею:\n"
        "• Загружать txt файлы с username\n"
        "• Отправлять их по очереди в канал\n"
        "• Настраивать задержку между отправками\n\n"
        "Выбери действие:",
        reply_markup=main_menu_kb()
    )


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🏠 Главное меню\n\nВыбери действие:",
        reply_markup=main_menu_kb()
    )


# ==================== ФАЙЛЫ ====================

@router.callback_query(F.data == "my_files")
async def show_files(callback: CallbackQuery):
    if not data["files"]:
        await callback.message.edit_text(
            "📁 У тебя пока нет загруженных файлов.\n\n"
            "Нажми «Загрузить файл» чтобы добавить.",
            reply_markup=back_kb()
        )
        return
    
    await callback.message.edit_text(
        "📁 Твои файлы:\n\n"
        "Выбери файл для просмотра или действий:",
        reply_markup=files_list_kb()
    )


@router.callback_query(F.data == "upload_file")
async def upload_file_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(States.waiting_file)
    await callback.message.edit_text(
        "📤 Отправь мне txt файл с username.\n\n"
        "📌 Формат файла:\n"
        "Каждый username с новой строки\n"
        "Можно с @ или без",
        reply_markup=cancel_kb()
    )


@router.message(States.waiting_file, F.document)
async def process_file(message: Message, state: FSMContext):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("❌ Пожалуйста, отправь txt файл!", reply_markup=cancel_kb())
        return
    
    # Скачиваем файл
    file = await bot.get_file(message.document.file_id)
    file_path = os.path.join(FILES_DIR, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    await bot.download_file(file.file_path, file_path)
    
    # Читаем и обрабатываем username
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    usernames = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if line:
            # Убираем @ если есть
            if line.startswith("@"):
                line = line[1:]
            usernames.append(line)
    
    if not usernames:
        await message.answer("❌ Файл пустой или не содержит username!", reply_markup=cancel_kb())
        os.remove(file_path)
        return
    
    # Сохраняем обработанные username
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(usernames))
    
    # Сохраняем информацию
    file_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    await state.update_data(temp_file_id=file_id, temp_file_path=file_path, temp_count=len(usernames))
    await state.set_state(States.waiting_file_name)
    
    await message.answer(
        f"✅ Файл загружен!\n"
        f"📊 Найдено username: {len(usernames)}\n\n"
        f"Введи название для этого файла:",
        reply_markup=cancel_kb()
    )


@router.message(States.waiting_file_name)
async def process_file_name(message: Message, state: FSMContext):
    file_name = message.text.strip()
    if not file_name:
        await message.answer("❌ Введи название!", reply_markup=cancel_kb())
        return
    
    state_data = await state.get_data()
    file_id = state_data["temp_file_id"]
    
    data["files"][file_id] = {
        "name": file_name,
        "path": state_data["temp_file_path"],
        "count": state_data["temp_count"],
        "uploaded": datetime.now().strftime('%d.%m.%Y %H:%M')
    }
    save_data()
    await state.clear()
    
    await message.answer(
        f"✅ Файл «{file_name}» сохранён!\n"
        f"📊 Username: {state_data['temp_count']}\n\n"
        f"Выбери действие:",
        reply_markup=main_menu_kb()
    )


@router.callback_query(F.data.startswith("select_file:"))
async def select_file(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    if file_id not in data["files"]:
        await callback.answer("❌ Файл не найден!")
        return
    
    file_info = data["files"][file_id]
    is_selected = "✅ ВЫБРАН ДЛЯ РАССЫЛКИ" if data["current_file"] == file_id else ""
    
    await callback.message.edit_text(
        f"📁 Файл: {file_info['name']}\n"
        f"📊 Username: {file_info['count']}\n"
        f"📅 Загружен: {file_info['uploaded']}\n"
        f"{is_selected}\n\n"
        f"Выбери действие:",
        reply_markup=file_actions_kb(file_id)
    )


@router.callback_query(F.data.startswith("choose_file:"))
async def choose_file_for_sending(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    data["current_file"] = file_id
    data["current_index"] = 0
    save_data()
    await callback.answer("✅ Файл выбран для рассылки!")
    await show_files(callback)


@router.callback_query(F.data.startswith("view_file:"))
async def view_file(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    if file_id not in data["files"]:
        await callback.answer("❌ Файл не найден!")
        return
    
    file_info = data["files"][file_id]
    with open(file_info["path"], "r", encoding="utf-8") as f:
        usernames = f.read().strip().split("\n")
    
    # Показываем первые 20 username
    preview = usernames[:20]
    preview_text = "\n".join([f"@{u}" for u in preview])
    
    more = f"\n\n... и ещё {len(usernames) - 20}" if len(usernames) > 20 else ""
    
    await callback.message.edit_text(
        f"👀 Просмотр файла «{file_info['name']}»:\n\n"
        f"{preview_text}{more}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"select_file:{file_id}")]
        ])
    )


@router.callback_query(F.data.startswith("delete_file:"))
async def delete_file_confirm(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    if file_id not in data["files"]:
        await callback.answer("❌ Файл не найден!")
        return
    
    await callback.message.edit_text(
        f"🗑 Удалить файл «{data['files'][file_id]['name']}»?",
        reply_markup=confirm_delete_kb(file_id)
    )


@router.callback_query(F.data.startswith("confirm_delete:"))
async def delete_file(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    if file_id in data["files"]:
        # Удаляем файл с диска
        if os.path.exists(data["files"][file_id]["path"]):
            os.remove(data["files"][file_id]["path"])
        del data["files"][file_id]
        if data["current_file"] == file_id:
            data["current_file"] = None
            data["current_index"] = 0
        save_data()
        await callback.answer("✅ Файл удалён!")
    
    await show_files(callback)


# ==================== ЗАДЕРЖКА ====================

@router.callback_query(F.data == "set_delay")
async def set_delay_menu(callback: CallbackQuery):
    current_delay = data["delay_seconds"]
    if current_delay >= 60:
        delay_text = f"{current_delay // 60} мин {current_delay % 60} сек"
    else:
        delay_text = f"{current_delay} сек"
    
    await callback.message.edit_text(
        f"⏱ Настройка задержки\n\n"
        f"Текущая задержка: {delay_text}\n\n"
        f"Выбери новую задержку:",
        reply_markup=delay_kb()
    )


@router.callback_query(F.data.startswith("delay:"))
async def set_delay(callback: CallbackQuery):
    seconds = int(callback.data.split(":")[1])
    data["delay_seconds"] = seconds
    save_data()
    
    if seconds >= 60:
        delay_text = f"{seconds // 60} мин {seconds % 60} сек"
    else:
        delay_text = f"{seconds} сек"
    
    await callback.answer(f"✅ Задержка: {delay_text}")
    await set_delay_menu(callback)


@router.callback_query(F.data == "delay_custom")
async def delay_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(States.waiting_delay)
    await callback.message.edit_text(
        "✏️ Введи задержку в секундах\n\n"
        "Примеры:\n"
        "• 30 - 30 секунд\n"
        "• 90 - 1 минута 30 секунд\n"
        "• 300 - 5 минут",
        reply_markup=cancel_kb()
    )


@router.message(States.waiting_delay)
async def process_custom_delay(message: Message, state: FSMContext):
    try:
        seconds = int(message.text.strip())
        if seconds < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число!", reply_markup=cancel_kb())
        return
    
    data["delay_seconds"] = seconds
    save_data()
    await state.clear()
    
    if seconds >= 60:
        delay_text = f"{seconds // 60} мин {seconds % 60} сек"
    else:
        delay_text = f"{seconds} сек"
    
    await message.answer(
        f"✅ Задержка установлена: {delay_text}",
        reply_markup=main_menu_kb()
    )


# ==================== КАНАЛ ====================

@router.callback_query(F.data == "set_channel")
async def set_channel_menu(callback: CallbackQuery, state: FSMContext):
    current = data["channel_id"]
    channel_text = f"Текущий канал: {current}" if current else "Канал не установлен"
    
    await state.set_state(States.waiting_channel)
    await callback.message.edit_text(
        f"📢 Настройка канала\n\n"
        f"{channel_text}\n\n"
        f"Отправь мне:\n"
        f"• @username канала\n"
        f"• Или ID канала (например: -1001234567890)\n\n"
        f"⚠️ Бот должен быть админом канала!",
        reply_markup=cancel_kb()
    )


@router.message(States.waiting_channel)
async def process_channel(message: Message, state: FSMContext):
    channel = message.text.strip()
    
    # Проверяем доступ к каналу
    try:
        chat = await bot.get_chat(channel)
        member = await bot.get_chat_member(channel, bot.id)
        if member.status not in ["administrator", "creator"]:
            await message.answer(
                "❌ Бот не является админом этого канала!\n"
                "Добавь бота как админа и попробуй снова.",
                reply_markup=cancel_kb()
            )
            return
    except Exception as e:
        await message.answer(
            f"❌ Не удалось получить доступ к каналу!\n"
            f"Ошибка: {e}\n\n"
            f"Проверь что:\n"
            f"• Канал существует\n"
            f"• Бот добавлен в канал как админ",
            reply_markup=cancel_kb()
        )
        return
    
    data["channel_id"] = channel
    save_data()
    await state.clear()
    
    await message.answer(
        f"✅ Канал установлен: {chat.title}\n"
        f"ID: {channel}",
        reply_markup=main_menu_kb()
    )


# ==================== РАССЫЛКА ====================

@router.callback_query(F.data == "start_sending")
async def start_sending(callback: CallbackQuery):
    global stop_flag
    
    if data["is_running"]:
        await callback.answer("⚠️ Рассылка уже запущена!")
        return
    
    if not data["channel_id"]:
        await callback.answer("❌ Сначала настрой канал!")
        return
    
    if not data["current_file"]:
        await callback.answer("❌ Сначала выбери файл!")
        return
    
    if data["current_file"] not in data["files"]:
        await callback.answer("❌ Выбранный файл не найден!")
        data["current_file"] = None
        save_data()
        return
    
    stop_flag = False
    data["is_running"] = True
    save_data()
    
    await callback.message.edit_text(
        "🚀 Рассылка запущена!\n\n"
        f"📁 Файл: {data['files'][data['current_file']]['name']}\n"
        f"⏱ Задержка: {data['delay_seconds']} сек\n"
        f"📢 Канал: {data['channel_id']}",
        reply_markup=main_menu_kb()
    )
    
    # Запускаем рассылку
    asyncio.create_task(sending_loop(callback.from_user.id))


async def sending_loop(admin_id: int):
    global stop_flag
    
    file_id = data["current_file"]
    file_info = data["files"][file_id]
    
    with open(file_info["path"], "r", encoding="utf-8") as f:
        usernames = f.read().strip().split("\n")
    
    start_index = data["current_index"]
    total = len(usernames)
    
    for i in range(start_index, total):
        if stop_flag:
            data["is_running"] = False
            data["current_index"] = i
            save_data()
            await bot.send_message(
                admin_id,
                f"🛑 Рассылка остановлена!\n\n"
                f"📊 Отправлено: {i}/{total}\n"
                f"📌 Продолжится с позиции {i + 1}",
                reply_markup=main_menu_kb()
            )
            return
        
        username = usernames[i]
        try:
            await bot.send_message(data["channel_id"], f"@{username}")
            data["current_index"] = i + 1
            save_data()
        except Exception as e:
            await bot.send_message(
                admin_id,
                f"⚠️ Ошибка при отправке @{username}: {e}"
            )
        
        # Прогресс каждые 10 сообщений
        if (i + 1) % 10 == 0:
            await bot.send_message(
                admin_id,
                f"📊 Прогресс: {i + 1}/{total}"
            )
        
        if i < total - 1:  # Не ждём после последнего
            await asyncio.sleep(data["delay_seconds"])
    
    # Рассылка завершена
    data["is_running"] = False
    data["current_index"] = 0
    save_data()
    
    await bot.send_message(
        admin_id,
        f"✅ Рассылка завершена!\n\n"
        f"📁 Файл: {file_info['name']}\n"
        f"📊 Отправлено: {total} username",
        reply_markup=main_menu_kb()
    )


@router.callback_query(F.data == "stop_sending")
async def stop_sending(callback: CallbackQuery):
    global stop_flag
    
    if not data["is_running"]:
        await callback.answer("⚠️ Рассылка не запущена!")
        return
    
    stop_flag = True
    await callback.answer("🛑 Останавливаю рассылку...")


# ==================== СТАТУС ====================

@router.callback_query(F.data == "status")
async def show_status(callback: CallbackQuery):
    delay = data["delay_seconds"]
    if delay >= 60:
        delay_text = f"{delay // 60} мин {delay % 60} сек"
    else:
        delay_text = f"{delay} сек"
    
    channel_text = data["channel_id"] if data["channel_id"] else "Не установлен"
    
    if data["current_file"] and data["current_file"] in data["files"]:
        file_text = data["files"][data["current_file"]]["name"]
        progress = f"Прогресс: {data['current_index']}/{data['files'][data['current_file']]['count']}"
    else:
        file_text = "Не выбран"
        progress = ""
    
    status = "🟢 Активна" if data["is_running"] else "🔴 Остановлена"
    
    await callback.message.edit_text(
        f"📊 Статус бота\n\n"
        f"Рассылка: {status}\n"
        f"📁 Файл: {file_text}\n"
        f"{progress}\n"
        f"⏱ Задержка: {delay_text}\n"
        f"📢 Канал: {channel_text}\n"
        f"📚 Всего файлов: {len(data['files'])}",
        reply_markup=main_menu_kb()
    )


# ==================== ЗАПУСК ====================

async def main():
    print("🤖 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
