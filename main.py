
import os
import time
import sqlite3
import threading
from datetime import timedelta
from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# === КОНФИГУРАЦИЯ ===
TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"                  # Смени на свой токен
CHANNEL_ID = -1002479611803                    # Смени на ID своего канала
DATABASE = "users.db"                          # БД для хранения файлов
FILE_DIR = "uploads"                            # Папка для временных файлов
os.makedirs(FILE_DIR, exist_ok=True)

# Задержка между отправками (в секундах)
DELAY = 20  # 5 секунд по умолчанию
DELAY_UNIT = "seconds"  # seconds или minutes

# === БД ===
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER,
            username TEXT NOT NULL,
            sent INTEGER DEFAULT 0,
            FOREIGN KEY(file_id) REFERENCES files(id)
        )
    ''')
    conn.commit()
    conn.close()

def save_file_to_db(filename):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO files (filename, status) VALUES (?, ?)", (filename, 'pending'))
        file_id = cursor.lastrowid
        conn.commit()
        return file_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def add_users_to_db(file_id, usernames):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    for username in usernames:
        username = username.strip()
        if username and username.startswith('@'):
            cursor.execute("INSERT INTO users (file_id, username) VALUES (?, ?)", (file_id, username))
    conn.commit()
    conn.close()

# === ПАРСИНГ ФАЙЛА ===
def parse_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line for line in f if line.strip() and line.strip().startswith('@')]

# === ОТПРАВКА В КАНАЛ ===
async def send_to_channel(username, context):
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=username)
        context.bot.logger.info(f"Отправлен: {username}")
        return True
    except Exception as e:
        context.bot.logger.error(f"Ошибка отправки {username}: {e}")
        return False

# === ОБРАБОТКА ФАЙЛА ===
async def process_file(file_id, context):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM files WHERE id = ?", (file_id,))
    filename = cursor.fetchone()[0]
    file_path = os.path.join(FILE_DIR, filename)
    
    usernames = parse_file(file_path)
    add_users_to_db(file_id, usernames)
    
    cursor.execute("UPDATE files SET status = 'processing' WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

    context.bot.logger.info(f"Началась обработка файла: {filename}, {len(usernames)} юзеров")
    
    # Отправка по очереди
    for username in usernames:
        if DELAY_UNIT == "minutes":
            time.sleep(DELAY * 60)
        else:
            time.sleep(DELAY)
        
        success = await send_to_channel(username, context)
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET sent = 1 WHERE file_id = ? AND username = ?", (file_id, username))
        conn.commit()
        conn.close()
    
    # Обновление статуса файла
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("UPDATE files SET status = 'completed' WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

    context.bot.logger.info(f"Файл {filename} обработан")

# === КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Загрузи `.txt`-файл с юзерами (по одному @username на строке).\n\n"
        "Команды:\n"
        "/start — начать\n"
        "/delay <seconds|minutes> <value> — установить задержку (например: /delay seconds 10 или /delay minutes 2)\n"
        "/status — статус файлов"
    )

async def delay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DELAY, DELAY_UNIT
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используй: /delay <seconds|minutes> <value>\nПример: /delay seconds 5")
        return
    unit, value_str = args
    if unit not in ["seconds", "minutes"]:
        await update.message.reply_text("Единица должна быть: seconds или minutes")
        return
    try:
        value = int(value_str)
        if value <= 0:
            await update.message.reply_text("Значение должно быть положительным")
            return
        DELAY = value
        DELAY_UNIT = unit
        await update.message.reply_text(f"Задержка установлена на {DELAY} {DELAY_UNIT}")
    except ValueError:
        await update.message.reply_text("Значение должно быть целым числом")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT f.filename, f.status, COUNT(u.id) as total, SUM(u.sent) as sent
        FROM files f
        LEFT JOIN users u ON f.id = u.file_id
        GROUP BY f.id
    ''')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Нет загруженных файлов")
        return

    msg = "📊 Статус файлов:\n\n"
    for filename, status, total, sent in rows:
        msg += f"📄 `{filename}`\n"
        msg += f"   Статус: {status.capitalize()}\n"
        msg += f"   Юзеров: {total}, Отправлено: {sent or 0}\n\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document and update.message.document.mime_type == "text/plain":
        file_id = update.message.document.file_id
        filename = update.message.document.file_name

        # Проверка расширения
        if not filename.lower().endswith('.txt'):
            await update.message.reply_text("Принимаются только файлы `.txt`")
            return

        file_path = os.path.join(FILE_DIR, filename)
        await context.bot.get_file(file_id).download_to_drive(file_path)

        file_db_id = save_file_to_db(filename)
        if not file_db_id:
            await update.message.reply_text(f"Файл {filename} уже обработан")
            return

        await update.message.reply_text(f"Файл `{filename}` загружен и добавлен в очередь")

        # Запускаем обработку в отдельном потоке, чтобы не блокировать бота
        threading.Thread(target=async_process_files, args=(context,), daemon=True).start()

    else:
        await update.message.reply_text("Пожалуйста, загрузите файл `.txt`")

async def async_process_files(context):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM files WHERE status = 'pending' ORDER BY id")
    pending_files = cursor.fetchall()
    conn.close()

    for (file_id,) in pending_files:
        await process_file(file_id, context)

    # Уведомление, когда все файлы обработаны
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Все файлы обработаны!"
    )

# === ОСНОВНОЙ КОД ===
async def main():
    init_db()
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("delay", delay_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(MessageHandler(filters.DOCUMENT & filters.MIME_TYPE("text/plain"), file_handler))

    await application.run_polling()

if __name__ == "__main__":
    # Создаем пустой файл базы данных, если не существует
    init_db()
    print("Бот запущен. Ждем файлов...")
    main()
