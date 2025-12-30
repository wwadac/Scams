import logging
import sqlite3
import socket
import sys
import os
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PreCheckoutQueryHandler, MessageHandler, filters
from datetime import datetime

BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"
ADMIN_ID = 6893832048

logging.basicConfig(level=logging.INFO)

def check_single_instance():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('localhost', 12345))
        return True
    except socket.error:
        print("❌ Бот уже запущен! pkill -f python")
        sys.exit(1)

check_single_instance()

def init_db():
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    charge_id TEXT,
    amount INTEGER,
    product_name TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    is_banned BOOLEAN DEFAULT FALSE,
    has_subscription BOOLEAN DEFAULT FALSE,
    join_date DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT
    )
    ''')
    cursor.execute('INSERT OR IGNORE INTO admin_settings (key, value) VALUES ("new_users_notifications", "on")')
    conn.commit()
    conn.close()

init_db()

# --- НАСТРОЙКА ТОВАРОВ ---
# Легко меняй названия и цены здесь!
PRODUCTS = {
    "premium": {"name": "🌟 Premium Подписка", "price": 70, "description": "Доступ к приватному каналу на 30 дней"},
    "video_100": {"name": "🎬 100 Видео", "price": 15, "description": "Пакет из 100 премиум видео"},
    "video_1000": {"name": "📹 1000 Видео", "price": 25, "description": "Пакет из 1000 премиум видео"},
    "video_10000": {"name": "🎥 10000 Видео + Канал", "price": 50, "description": "10000 видео + доступ к каналу"}
}
# --- КОНЕЦ НАСТРОЙКИ ТОВАРОВ ---

def get_admin_setting(key):
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "on"

def set_admin_setting(key, value):
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO admin_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    try:
        await context.bot.send_message(ADMIN_ID, message, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Ошибка отправки админу: {e}")

# Команда для скачивания базы данных
async def download_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    try:
        # Создаем временную копию базы данных
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
            temp_path = temp_file.name
        
        # Копируем базу данных во временный файл
        import shutil
        shutil.copy2('payments.db', temp_path)
        
        # Отправляем файл
        with open(temp_path, 'rb') as db_file:
            await update.message.reply_document(
                document=db_file,
                filename='payments.db',
                caption='📦 База данных бота'
            )
        
        # Удаляем временный файл
        os.unlink(temp_path)
        
        await update.message.reply_text("✅ База данных успешно отправлена!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при выгрузке базы данных: {e}")

# Команда для загрузки базы данных
async def upload_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    if not update.message.document:
        await update.message.reply_text("❌ Пожалуйста, отправьте файл базы данных (.db)")
        return

    document = update.message.document

    # Проверяем что это файл базы данных
    if not document.file_name.endswith('.db'):
        await update.message.reply_text("❌ Пожалуйста, отправьте файл с расширением .db")
        return

    try:
        # Скачиваем файл
        file = await context.bot.get_file(document.file_id)
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
            temp_path = temp_file.name
        
        # Скачиваем во временный файл
        await file.download_to_drive(temp_path)
        
        # Проверяем что файл является валидной SQLite базой
        try:
            test_conn = sqlite3.connect(temp_path)
            test_cursor = test_conn.cursor()
            
            # Проверяем наличие основных таблиц
            test_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'payments', 'admin_settings')")
            tables = test_cursor.fetchall()
            
            if len(tables) < 3:
                await update.message.reply_text("❌ Файл не содержит все необходимые таблицы!")
                os.unlink(temp_path)
                return
                
            test_conn.close()
            
        except sqlite3.Error as e:
            await update.message.reply_text(f"❌ Файл не является валидной SQLite базой данных: {e}")
            os.unlink(temp_path)
            return
        
        # Создаем бэкап текущей базы
        backup_path = f'payments_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        import shutil
        shutil.copy2('payments.db', backup_path)
        
        # Заменяем текущую базу данных
        shutil.copy2(temp_path, 'payments.db')
        
        # Удаляем временный файл
        os.unlink(temp_path)
        
        await update.message.reply_text(
            f"✅ База данных успешно обновлена!\n"
            f"📁 Бэкап сохранен как: {backup_path}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при загрузке базы данных: {e}")

# Команда для создания бэкапа
async def backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    try:
        backup_path = f'payments_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        import shutil
        shutil.copy2('payments.db', backup_path)
        
        # Отправляем бэкап
        with open(backup_path, 'rb') as backup_file:
            await update.message.reply_document(
                document=backup_file,
                filename=os.path.basename(backup_path),
                caption='💾 Бэкап базы данных'
            )
        
        await update.message.reply_text("✅ Бэкап создан и отправлен!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при создании бэкапа: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user.id,))
    existing_user = cursor.fetchone()

    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                   (user.id, user.username, user.first_name))
    conn.commit()
    conn.close()

    if not existing_user and get_admin_setting("new_users_notifications") == "on":
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"""🆕 *НОВЫЙ ПОЛЬЗОВАТЕЛЬ*

    👤 Имя: {user.first_name}
    📛 Ник: @{user.username or 'нет'}
    🆔 ID: {user.id}
    🕐 Время: {current_time}"""
        await notify_admin(context, message)

    keyboard = [
        [InlineKeyboardButton(f"{PRODUCTS['premium']['name']} - {PRODUCTS['premium']['price']} звезд", callback_data="premium")],
        [InlineKeyboardButton("📁 Видео", callback_data="videos")],
        [InlineKeyboardButton("💬 Тех. Поддержка", callback_data="support")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = """🛍️ *Добро пожаловать в магазин!*

    Выберите раздел:"""
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "videos":
        keyboard = [
            [InlineKeyboardButton(f"{PRODUCTS['video_100']['name']} - {PRODUCTS['video_100']['price']} звезд", callback_data="video_100")],
            [InlineKeyboardButton(f"{PRODUCTS['video_1000']['name']} - {PRODUCTS['video_1000']['price']} звезд", callback_data="video_1000")],
            [InlineKeyboardButton(f"{PRODUCTS['video_10000']['name']} - {PRODUCTS['video_10000']['price']} звезд", callback_data="video_10000")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📁 *Раздел с видео*\n\nВыберите пакет:", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == "support":
        context.user_data['awaiting_support'] = True
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = """💬 *Техническая поддержка*

    Напишите ваш вопрос и администратор скоро ответит.

    Просто напишите сообщение с вашим вопросом:"""
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == "about":
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = """🎁 ЭкcклюzивHый koHтeHт, kotopый Bы He H@йдеTe бoльwе Hигде

    Этoт бот oткpывает двеpи к HеoгpaHиченHому пoтoky экcклюzивHогo koHтeHта, дocтуп к kotopому Bы мoжеtе пoлyчить t
