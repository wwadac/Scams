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
    CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT NOT NULL
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT
    )
    ''')
    
    # Инициализация товаров по умолчанию
    default_products = [
        ("premium", "🌟 Premium Подписка", 70, "Доступ к приватному каналу на 30 дней"),
        ("video_100", "🎬 100 Видео", 15, "Пакет из 100 премиум видео"),
        ("video_1000", "📹 1000 Видео", 25, "Пакет из 1000 премиум видео"),
        ("video_10000", "🎥 10000 Видео + Канал", 50, "10000 видео + доступ к каналу")
    ]
    
    cursor.executemany(
        'INSERT OR IGNORE INTO products (id, name, price, description) VALUES (?, ?, ?, ?)',
        default_products
    )
    cursor.execute('INSERT OR IGNORE INTO admin_settings (key, value) VALUES ("new_users_notifications", "on")')
    conn.commit()
    conn.close()

init_db()

def get_products():
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, price, description FROM products')
    products = cursor.fetchall()
    conn.close()
    return {p[0]: {"name": p[1], "price": p[2], "description": p[3]} for p in products}

def update_product(product_id, name, price, description):
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE products SET name = ?, price = ?, description = ? WHERE id = ?',
        (name, price, description, product_id)
    )
    conn.commit()
    conn.close()

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
            test_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'payments', 'admin_settings', 'products')")
            tables = test_cursor.fetchall()
            
            if len(tables) < 4:
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

    products = get_products()
    keyboard = [
        [InlineKeyboardButton(f"{products['premium']['name']} - {products['premium']['price']} звезд", callback_data="premium")],
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

    products = get_products()
    
    if query.data == "videos":
        keyboard = [
            [InlineKeyboardButton(f"{products['video_100']['name']} - {products['video_100']['price']} звезд", callback_data="video_100")],
            [InlineKeyboardButton(f"{products['video_1000']['name']} - {products['video_1000']['price']} звезд", callback_data="video_1000")],
            [InlineKeyboardButton(f"{products['video_10000']['name']} - {products['video_10000']['price']} звезд", callback_data="video_10000")],
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
        text = """🎁 Экcклюзивный контент, который вы не найдете больше нигде

    Этот бот открывает двери к неограниченному потоку эксклюзивного контента, доступ к которому вы можете получить только у нас! Мы предлагаем доступные, безопасные и анонимные услуги.

    🌟 Premium-Подписка
    Доступ к приватному каналу с более чем 30.000 тысяч видео подобного характера. В случае удаления основного канала, мы готовы предоставить вам доступ к дополнительному!

    📁 Видео-пакеты
    Различные пакеты видеоматериалов по привлекательным ценам. Рассматривайте это как возможность опробовать наши услуги перед тем, как приобрести подписку.

    Возрастные ограничения: от 14 до 18 лет."""
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == "back_main":
        context.user_data.pop('awaiting_support', None)
        keyboard = [
            [InlineKeyboardButton(f"{products['premium']['name']} - {products['premium']['price']} звезд", callback_data="premium")],
            [InlineKeyboardButton("📁 Видео", callback_data="videos")],
            [InlineKeyboardButton("💬 Тех. Поддержка", callback_data="support")],
            [InlineKeyboardButton("ℹ️ О боте", callback_data="about")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🛍️ *Добро пожаловать в магазин!*\n\nВыберите раздел:", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data in products:
        product = products[query.data]
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=product["name"],
            description=product["description"],
            payload=query.data,
            currency="XTR",
            prices=[{"label": "Stars", "amount": product["price"]}],
        )

# Админские команды
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📦 Управление товарами", callback_data="manage_products")],
        [InlineKeyboardButton("📢 Быстрая рассылка", callback_data="quick_broadcast")],
        [InlineKeyboardButton("🔔 Уведомления ВКЛ", callback_data="notifications_off"), 
         InlineKeyboardButton("🔕 Уведомления ВЫКЛ", callback_data="notifications_on")],
        [InlineKeyboardButton("👥 Все пользователи", callback_data="all_users")],
        [InlineKeyboardButton("💾 Управление БД", callback_data="db_management")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = """👑 *Панель администратора*

    Выберите действие:"""
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "admin_stats":
        conn = sqlite3.connect('payments.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM payments')
        total_payments = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(amount) FROM payments')
        total_stars = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE has_subscription = TRUE')
        premium_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE DATE(join_date) = DATE("now")')
        new_today = cursor.fetchone()[0]
        
        conn.close()

        text = f"""📊 *Статистика за все время*

    👥 Всего пользователей: {total_users}
    💎 Премиум пользователей: {premium_users}
    💰 Всего платежей: {total_payments}
    ⭐ Всего звезд: {total_stars}
    🆕 Новых сегодня: {new_today}"""

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == "manage_products":
        products = get_products()
        keyboard = []
        for prod_id, details in products.items():
            keyboard.append([InlineKeyboardButton(f"✏️ {details['name']}", callback_data=f"edit_{prod_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_admin")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📦 *Управление товарами*\n\nВыберите товар для редактирования:", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data.startswith("edit_"):
        prod_id = query.data[5:]
        context.user_data['editing_product'] = prod_id
        products = get_products()
        product = products[prod_id]
        
        text = f"""✏️ *Редактирование товара*

    ID: `{prod_id}`
    Название: `{product['name']}`
    Цена: `{product['price']}`
    Описание: `{product['description']}`

    Отправьте новое название (в формате: название|цена|описание):"""
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="manage_products")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        context.user_data['awaiting_product_edit'] = True

    elif query.data == "quick_broadcast":
        context.user_data['awaiting_broadcast'] = True
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📢 *Быстрая рассылка*\n\nВведите сообщение для рассылки:", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == "notifications_on":
        set_admin_setting("new_users_notifications", "on")
        await query.edit_message_text("✅ Уведомления о новых пользователях ВКЛЮЧЕНЫ")

    elif query.data == "notifications_off":
        set_admin_setting("new_users_notifications", "off")
        await query.edit_message_text("✅ Уведомления о новых пользователях ВЫКЛЮЧЕНЫ")

    elif query.data == "all_users":
        conn = sqlite3.connect('payments.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, join_date FROM users ORDER BY join_date DESC')
        users = cursor.fetchall()
        conn.close()

        if not users:
            await query.edit_message_text("📭 Пользователей нет")
            return

        text = f"👥 *Все пользователи ({len(users)}):*\n\n"
        for user in users:
            user_id, username, first_name, join_date = user
            text += f"👤 {first_name} (@{username or 'нет'})\n🆔 {user_id}\n🕐 {join_date}\n\n"

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Разбиваем сообщение если слишком длинное
        if len(text) > 4096:
            parts = [text[i:i+4096] for i in range(0, len(text), 4096)]
            await query.edit_message_text(parts[0], reply_markup=reply_markup)
            for part in parts[1:]:
                await context.bot.send_message(chat_id=query.message.chat_id, text=part)
        else:
            await query.edit_message_text(text, reply_markup=reply_markup)

    elif query.data == "db_management":
        keyboard = [
            [InlineKeyboardButton("📥 Скачать БД", callback_data="download_db")],
            [InlineKeyboardButton("💾 Создать бэкап", callback_data="backup_db")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("💾 *Управление базой данных*\n\nВыберите действие:", reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == "download_db":
        await query.edit_message_text("📥 Скачиваю базу данных...")
        await download_db_callback(update, context)

    elif query.data == "backup_db":
        await query.edit_message_text("💾 Создаю бэкап...")
        await backup_db_callback(update, context)

    elif query.data == "back_admin":
        await admin_panel_callback(update, context)

async def download_db_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        # Создаем временную копию базы данных
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
            temp_path = temp_file.name

        # Копируем базу данных во временный файл
        import shutil
        shutil.copy2('payments.db', temp_path)
        
        # Отправляем файл
        with open(temp_path, 'rb') as db_file:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=db_file,
                filename='payments.db',
                caption='📦 База данных бота'
            )
        
        # Удаляем временный файл
        os.unlink(temp_path)
        
        await query.edit_message_text("✅ База данных успешно отправлена!")
        
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка при выгрузке базы данных: {e}")

async def backup_db_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        backup_path = f'payments_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        import shutil
        shutil.copy2('payments.db', backup_path)

        # Отправляем бэкап
        with open(backup_path, 'rb') as backup_file:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=backup_file,
                filename=os.path.basename(backup_path),
                caption='💾 Бэкап базы данных'
            )
        
        await query.edit_message_text("✅ Бэкап создан и отправлен!")
        
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка при создании бэкапа: {e}")

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📦 Управление товарами", callback_data="manage_products")],
        [InlineKeyboardButton("📢 Быстрая рассылка", callback_data="quick_broadcast")],
        [InlineKeyboardButton("🔔 Уведомления ВКЛ", callback_data="notifications_off"), 
         InlineKeyboardButton("🔕 Уведомления ВЫКЛ", callback_data="notifications_on")],
        [InlineKeyboardButton("👥 Все пользователи", callback_data="all_users")],
        [InlineKeyboardButton("💾 Управление БД", callback_data="db_management")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = """👑 *Панель администратора*

    Выберите действие:"""
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Обработчик текстовых сообщений
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if context.user_data.get('awaiting_support'):
        user = update.message.from_user
        question = update.message.text

        admin_msg = f"""💬 *НОВЫЙ ВОПРОС В ТЕХПОДДЕРЖКУ*

    👤 Пользователь: {user.first_name} (@{user.username or 'нет'})
    🆔 ID: {user.id}
    🕐 Время: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    ❓ Вопрос:
    {question}"""

        await notify_admin(context, admin_msg)
        await update.message.reply_text("✅ Ваш вопрос отправлен администратору. Ожидайте ответа в ближайшее время!")
        context.user_data.pop('awaiting_support', None)

    elif context.user_data.get('awaiting_broadcast') and user_id == ADMIN_ID:
        message = update.message.text
        conn = sqlite3.connect('payments.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE is_banned = FALSE')
        users = cursor.fetchall()
        conn.close()

        sent = 0
        failed = 0
        for user in users:
            try:
                await context.bot.send_message(user[0], f"📢 *Рассылка:*\n\n{message}", parse_mode='Markdown')
                sent += 1
            except:
                failed += 1

        context.user_data.pop('awaiting_broadcast', None)
        await update.message.reply_text(f"✅ Рассылка завершена!\n\n📤 Отправлено: {sent}\n❌ Не отправлено: {failed}")

    # Обработка редактирования товара
    elif context.user_data.get('awaiting_product_edit') and user_id == ADMIN_ID:
        try:
            parts = update.message.text.split('|')
            if len(parts) != 3:
                await update.message.reply_text("❌ Формат: название|цена|описание")
                return
                
            name, price_str, description = parts
            price = int(price_str)
            
            product_id = context.user_data['editing_product']
            update_product(product_id, name.strip(), price, description.strip())
            
            await update.message.reply_text(f"✅ Товар обновлён:\n\nНазвание: {name}\nЦена: {price}\nОписание: {description}")
            context.user_data.pop('awaiting_product_edit', None)
            context.user_data.pop('editing_product', None)
            
        except ValueError:
            await update.message.reply_text("❌ Цена должна быть числом")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    # Обработка ответов админа на вопросы
    elif context.user_data.get('awaiting_reply') and user_id == ADMIN_ID:
        user_id_to_reply = context.user_data.get('reply_user_id')
        message = update.message.text
        
        try:
            await context.bot.send_message(
                user_id_to_reply, 
                f"💬 *ОТВЕТ АДМИНИСТРАТОРА:*\n\n{message}", 
                parse_mode='Markdown'
            )
            await update.message.reply_text(f"✅ Ответ отправлен пользователю {user_id_to_reply}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка отправки: {e}")
        
        context.user_data.pop('awaiting_reply', None)
        context.user_data.pop('reply_user_id', None)

# Команда для ответа на вопросы техподдержки
async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Используй: /reply <user_id> <сообщение>")
        return

    try:
        user_id = int(context.args[0])
        message = ' '.join(context.args[1:])

        await context.bot.send_message(
            user_id, 
            f"💬 *ОТВЕТ АДМИНИСТРАТОРА:*\n\n{message}", 
            parse_mode='Markdown'
        )
        await update.message.reply_text(f"✅ Ответ отправлен пользователю {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# Команда для отправки сообщения от имени администратора
async def tell_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Используй: /tell <user_id> <сообщение>")
        return

    try:
        user_id = int(context.args[0])
        message = ' '.join(context.args[1:])

        await context.bot.send_message(
            user_id, 
            f"👑 *АДМИНИСТРАТОР:*\n\n{message}", 
            parse_mode='Markdown'
        )
        await update.message.reply_text(f"✅ Сообщение отправлено пользователю {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user = update.message.from_user
    products = get_products()

    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (user_id, username, first_name, charge_id, amount, product_name)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user.id, user.username, user.first_name, payment.telegram_payment_charge_id,
          payment.total_amount, payment.invoice_payload))

    if payment.invoice_payload == "premium":
        cursor.execute('UPDATE users SET has_subscription = TRUE WHERE user_id = ?', (user.id,))

    conn.commit()
    conn.close()

    admin_msg = f"""💰 *НОВАЯ ОПЛАТА*

    👤 Пользователь: {user.first_name} (@{user.username or 'нет'})
    🆔 ID: {user.id}
    📦 Товар: {products[payment.invoice_payload]['name']}
    💎 Сумма: {payment.total_amount} звезд
    🆔 Charge ID: {payment.telegram_payment_charge_id}
    🕐 Время: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""

    await notify_admin(context, admin_msg)

    user_msg = f"""✅ *Оплата прошла успешно!*

    📦 Товар: {products[payment.invoice_payload]['name']}
    💎 Сумма: {payment.total_amount} звезд

    Спасибо за покупку! 🎉"""

    await update.message.reply_text(user_msg, parse_mode='Markdown')

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Основные команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))

    # Новые команды для админа
    application.add_handler(CommandHandler("reply", reply_to_user))
    application.add_handler(CommandHandler("tell", tell_user))
    application.add_handler(CommandHandler("download_db", download_db))
    application.add_handler(CommandHandler("backup_db", backup_db))
    application.add_handler(CommandHandler("upload_db", upload_db))

    # Обработчики callback
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(premium|videos|support|about|back_main|video_100|video_1000|video_10000)$"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(admin_stats|manage_products|quick_broadcast|notifications_on|notifications_off|all_users|back_admin|db_management|download_db|backup_db|edit_.*)$"))

    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    application.add_handler(MessageHandler(filters.Document.ALL, upload_db))  # Обработчик загрузки файлов
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    application.run_polling()

if __name__ == "__main__":
    main()
