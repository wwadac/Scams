import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, 
    CallbackQuery, 
    LabeledPrice, 
    PreCheckoutQuery
)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Токен бота (замените на свой)
BOT_TOKEN = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"

# Создаём роутер
router = Router()


# ==================== КЛАВИАТУРЫ ====================

def payment_keyboard(amount: int):
    """Клавиатура с кнопкой оплаты"""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"��платить {amount} ⭐️", pay=True)
    return builder.as_markup()


def donate_options_keyboard():
    """Клавиатура с вариантами донатов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="10 ⭐️", callback_data="donate_10")
    builder.button(text="50 ⭐️", callback_data="donate_50")
    builder.button(text="100 ⭐️", callback_data="donate_100")
    builder.button(text="500 ⭐️", callback_data="donate_500")
    builder.adjust(2)
    return builder.as_markup()


# ==================== ОБРАБОТЧИКИ ====================

@router.message(Command("start"))
async def start_handler(message: Message):
    """Приветственное сообщение"""
    await message.answer(
        text=f"👋 Привет, {message.from_user.first_name}!\n\n"
             f"Я бот для приёма донатов через Telegram Stars ⭐️\n\n"
             f"<b>Команды:</b>\n"
             f"/donate - Сделать донат\n"
             f"/paysupport - Поддержка по платежам",
        parse_mode="HTML"
    )


@router.message(Command("donate"))
async def donate_command_handler(message: Message):
    """Показывает варианты донатов"""
    await message.answer(
        text="🌟 <b>Поддержите проект!</b>\n\n"
             "Выберите сумму доната:",
        reply_markup=donate_options_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("donate_"))
async def send_invoice_handler(callback: CallbackQuery):
    """Выставляет счёт на оплату"""
    amount = int(callback.data.split("_")[1])
    
    prices = [LabeledPrice(label="XTR", amount=amount)]
    
    await callback.message.answer_invoice(
        title="Донат на развитие проекта",
        description=f"Поддержать проект на {amount} звёзд! ⭐️",
        prices=prices,
        provider_token="",
        payload=f"donate_{amount}",
        currency="XTR",
        reply_markup=payment_keyboard(amount),
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Подтверждаем возможность оплаты"""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def success_payment_handler(message: Message):
    """Обрабатываем успешную оплату"""
    amount = message.successful_payment.total_amount
    payment_id = message.successful_payment.telegram_payment_charge_id
    
    logging.info(f"Донат {amount} ⭐️ от {message.from_user.id}, ID: {payment_id}")
    
    await message.answer(
        text=f"🎉 <b>Спасибо за донат!</b>\n\n"
             f"Вы поддержали проект на {amount} ⭐️\n"
             f"Ваша поддержка очень важна! 💖",
        parse_mode="HTML"
    )


@router.message(Command("paysupport"))
async def pay_support_handler(message: Message):
    """Информация о возврате средств"""
    await message.answer(
        text="💬 <b>Поддержка по платежам</b>\n\n"
             "Донаты являются добровольными и "
             "не подразумевают возврат средств.\n\n"
             "При проблемах пишите: @your_support",
        parse_mode="HTML"
    )


# ==================== ЗАПУСК ====================

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())