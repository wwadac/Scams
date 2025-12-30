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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"
ADMIN_ID = 6893832048

router = Router()
bot: Bot = None

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect('shop.db', check_same_thread=False)
cursor = conn.cursor()

cursor.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        join_date TEXT
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        amount INTEGER,
        charge_id TEXT,
        date TEXT
    );
''')
conn.commit()


# ==================== FSM СОСТОЯНИЯ ====================
class AdminStates(StatesGroup):
    waiting_product_name = State()
    waiting_product_price = State()
    waiting_new_product = State()
    waiting_broadcast = State()


# ==================== КЛАВИАТУРЫ ====================
def get_shop_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура магазина для пользователей"""
    builder = InlineKeyboardBuilder()
    
    cursor.execute("SELECT id, name, price FROM products ORDER BY id")
    products = cursor.fetchall()
    
    for prod_id, name, price in products:
        builder.button(
            text=f"{name} — {price}⭐",
            callback_data=f"buy:{prod_id}"
        )
    
    builder.button(text="📋 Мои покупки", callback_data="my_purchases")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Главное меню админ-панели"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Управление товарами", callback_data="admin:products")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin:add")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
    ])


def get_products_list_keyboard() -> InlineKeyboardMarkup:
    """Список товаров для редактирования"""
    builder = InlineKeyboardBuilder()
    
    cursor.execute("SELECT id, name, price FROM products ORDER BY id")
    products = cursor.fetchall()
    
    for prod_id, name, price in products:
        builder.button(
            text=f"📦 {name} ({price}⭐)",
            callback_data=f"admin:edit:{prod_id}"
        )
    
    builder.button(text="◀️ Назад", callback_data="admin:menu")
    builder.adjust(1)
    return builder.as_markup()


def get_edit_product_keyboard(product_id: int) -> InlineKeyboardMarkup:
    """Клавиатура редактирования товара"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Название", callback_data=f"admin:name:{product_id}"),
            InlineKeyboardButton(text="💰 Цена", callback_data=f"admin:price:{product_id}")
        ],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:del:{product_id}")],
        [InlineKeyboardButton(text="◀️ К списку", callback_data="admin:products")]
    ])


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
    ])


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:menu")]
    ])


# ==================== ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ ====================
@router.message(CommandStart())
async def cmd_start(message: Message):
    """Стартовая команда"""
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)",
        (message.from_user.id, message.from_user.username, datetime.now().isoformat())
    )
    conn.commit()
    
    await message.answer(
        "🛍 <b>Добро пожаловать в магазин!</b>\n\n"
        "Выберите товар из списка ниже:",
        reply_markup=get_shop_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("buy:"))
async def process_purchase(callback: CallbackQuery):
    """Обработка покупки"""
    product_id = int(callback.data.split(":")[1])
    
    cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
    result = cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return
    
    name, price = result
    
    await callback.message.answer_invoice(
        title=f"Покупка: {name}",
        description=f"Оплата товара «{name}»",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=name, amount=price)],
        payload=f"buy:{product_id}"
    )
    await callback.answer()


@router.callback_query(F.data == "my_purchases")
async def show_purchases(callback: CallbackQuery):
    """Показать историю покупок"""
    cursor.execute(
        """SELECT p.name, pay.amount, pay.date 
           FROM payments pay 
           JOIN products p ON pay.product_id = p.id 
           WHERE pay.user_id = ? 
           ORDER BY pay.date DESC LIMIT 10""",
        (callback.from_user.id,)
    )
    purchases = cursor.fetchall()
    
    if not purchases:
        await callback.answer("📭 У вас пока нет покупок", show_alert=True)
        return
    
    text = "📋 <b>Ваши последние покупки:</b>\n\n"
    for name, amount, date in purchases:
        text += f"• {name} — {amount}⭐ ({date[:10]})\n"
    
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Подтверждение оплаты"""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    """Успешная оплата"""
    payment = message.successful_payment
    product_id = int(payment.invoice_payload.split(":")[1])
    
    cursor.execute(
        "INSERT INTO payments (user_id, product_id, amount, charge_id, date) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, product_id, payment.total_amount, 
         payment.telegram_payment_charge_id, datetime.now().isoformat())
    )
    conn.commit()
    
    cursor.execute("SELECT name FROM products WHERE id = ?", (product_id,))
    product_name = cursor.fetchone()[0]
    
    await message.answer(
        f"✅ <b>Оплата успешна!</b>\n\n"
        f"📦 Товар: {product_name}\n"
        f"💰 Сумма: {payment.total_amount}⭐\n"
        f"🆔 Транзакция: <code>{payment.telegram_payment_charge_id}</code>\n\n"
        "Спасибо за покупку! 🎉",
        parse_mode="HTML"
    )


# ==================== АДМИН-ПАНЕЛЬ ====================
def is_admin(user_id: int) -> bool:
    """Проверка на админа"""
    return user_id == ADMIN_ID


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Вход в админ-панель"""
    if not is_admin(message.from_user.id):
        return
    
    await state.clear()
    await message.answer(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext):
    """Главное меню админки"""
    if not is_admin(callback.from_user.id):
        return
    
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена действия"""
    if not is_admin(callback.from_user.id):
        return
    
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено\n\n⚙️ <b>Админ-панель</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


# --- Управление товарами ---
@router.callback_query(F.data == "admin:products")
async def admin_products(callback: CallbackQuery):
    """Список товаров"""
    if not is_admin(callback.from_user.id):
        return
    
    cursor.execute("SELECT COUNT(*) FROM products")
    count = cursor.fetchone()[0]
    
    await callback.message.edit_text(
        f"📦 <b>Управление товарами</b>\n\nВсего товаров: {count}\n\nВыберите товар для редактирования:",
        reply_markup=get_products_list_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:edit:"))
async def admin_edit_product(callback: CallbackQuery):
    """Меню редактирования товара"""
    if not is_admin(callback.from_user.id):
        return
    
    product_id = int(callback.data.split(":")[2])
    
    cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
    result = cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return
    
    name, price = result
    
    await callback.message.edit_text(
        f"📦 <b>Редактирование товара</b>\n\n"
        f"🆔 ID: <code>{product_id}</code>\n"
        f"📝 Название: <code>{name}</code>\n"
        f"💰 Цена: <code>{price}⭐</code>\n\n"
        f"Выберите что изменить:",
        reply_markup=get_edit_product_keyboard(product_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:name:"))
async def admin_change_name(callback: CallbackQuery, state: FSMContext):
    """Начало изменения названия"""
    if not is_admin(callback.from_user.id):
        return
    
    product_id = int(callback.data.split(":")[2])
    
    await state.set_state(AdminStates.waiting_product_name)
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text(
        "✏️ <b>Изменение названия</b>\n\nОтправьте новое название товара:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_product_name)
async def process_new_name(message: Message, state: FSMContext):
    """Обработка нового названия"""
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    product_id = data["product_id"]
    new_name = message.text.strip()
    
    cursor.execute("UPDATE products SET name = ? WHERE id = ?", (new_name, product_id))
    conn.commit()
    
    await state.clear()
    await message.answer(
        f"✅ Название изменено на: <code>{new_name}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:price:"))
async def admin_change_price(callback: CallbackQuery, state: FSMContext):
    """Начало изменения цены"""
    if not is_admin(callback.from_user.id):
        return
    
    product_id = int(callback.data.split(":")[2])
    
    await state.set_state(AdminStates.waiting_product_price)
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text(
        "💰 <b>Изменение цены</b>\n\nОтправьте новую цену (целое число):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_product_price)
async def process_new_price(message: Message, state: FSMContext):
    """Обработка новой цены"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        new_price = int(message.text.strip())
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число!")
        return
    
    data = await state.get_data()
    product_id = data["product_id"]
    
    cursor.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, product_id))
    conn.commit()
    
    await state.clear()
    await message.answer(
        f"✅ Цена изменена на: <code>{new_price}⭐</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:del:"))
async def admin_delete_product(callback: CallbackQuery):
    """Удаление товара"""
    if not is_admin(callback.from_user.id):
        return
    
    product_id = int(callback.data.split(":")[2])
    
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    
    await callback.answer("🗑 Товар удалён!", show_alert=True)
    
    # Возврат к списку товаров
    await callback.message.edit_text(
        "📦 <b>Управление товарами</b>\n\nВыберите товар для редактирования:",
        reply_markup=get_products_list_keyboard(),
        parse_mode="HTML"
    )


# --- Добавление товара ---
@router.callback_query(F.data == "admin:add")
async def admin_add_product(callback: CallbackQuery, state: FSMContext):
    """Начало добавления товара"""
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state(AdminStates.waiting_new_product)
    
    await callback.message.edit_text(
        "➕ <b>Добавление товара</b>\n\n"
        "Отправьте данные в формате:\n"
        "<code>Название | Цена</code>\n\n"
        "Пример: <code>VIP доступ | 100</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_new_product)
async def process_new_product(message: Message, state: FSMContext):
    """Обработка нового товара"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split("|")
        if len(parts) != 2:
            raise ValueError("Неверный формат")
        
        name = parts[0].strip()
        price = int(parts[1].strip())
        
        if not name or price <= 0:
            raise ValueError("Пустое название или неверная цена")
        
        cursor.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
        conn.commit()
        
        await state.clear()
        await message.answer(
            f"✅ <b>Товар добавлен!</b>\n\n"
            f"📝 Название: <code>{name}</code>\n"
            f"💰 Цена: <code>{price}⭐</code>",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        await message.answer(
            "❌ <b>Ошибка формата!</b>\n\n"
            "Используйте: <code>Название | Цена</code>",
            parse_mode="HTML"
        )


# --- Статистика ---
@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    """Статистика бота"""
    if not is_admin(callback.from_user.id):
        return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM products")
    products_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments")
    payments_count, total_stars = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE date(join_date) = date('now')")
    today_users = cursor.fetchone()[0]
    
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <code>{users_count}</code>\n"
        f"🆕 Новых сегодня: <code>{today_users}</code>\n"
        f"📦 Товаров: <code>{products_count}</code>\n"
        f"💳 Платежей: <code>{payments_count}</code>\n"
        f"⭐ Заработано звёзд: <code>{total_stars}</code>",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )


# --- Рассылка ---
@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if not is_admin(callback.from_user.id):
        return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    
    await state.set_state(AdminStates.waiting_broadcast)
    
    await callback.message.edit_text(
        f"📢 <b>Рассылка</b>\n\n"
        f"Получателей: <code>{users_count}</code>\n\n"
        f"Отправьте текст для рассылки:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    """Выполнение рассылки"""
    if not is_admin(message.from_user.id):
        return
    
    await state.clear()
    
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    
    status_msg = await message.answer("📤 <b>Рассылка началась...</b>", parse_mode="HTML")
    
    success = 0
    failed = 0
    
    for (user_id,) in users:
        try:
            await bot.send_message(user_id, message.text)
            success += 1
        except Exception:
            failed += 1
        
        # Небольшая задержка чтобы не превысить лимиты
        if (success + failed) % 25 == 0:
            await asyncio.sleep(1)
    
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Успешно: <code>{success}</code>\n"
        f"❌ Ошибок: <code>{failed}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


# ==================== ЗАПУСК БОТА ====================
async def main():
    global bot
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    logging.info("✅ Бот запущен!")
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
