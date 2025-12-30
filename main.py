
import asyncio
import logging
import re
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ----------------------------------------------------------------------
# Настройки логирования (удобно при отладке)
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------
def parse_delay(text: str) -> int:
    """
    Преобразует строку вида "5s", "2m", "10" → количество секунд.
    Если формат не rozпознан – возвращает 1 (минимальная задержка).
    """
    text = text.strip().lower()
    if text.endswith("s"):
        return int(text[:-1]) if text[:-1] else 1
    if text.endswith("m"):
        return int(text[:-1]) * 60 if text[:-1] else 60
    return int(text) if text.isdigit() else 1


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие и короткая справка."""
    await update.message.reply_text(
        "👋 Я бот‑парсер для рассылки никнеймов в канал.\n"
        "📂 Пришли мне *.txt*‑файл с username‑ами (по одной строке).\n"
        "🔧 Сначалаукайте /setchannel <имя_канала> и /setdelay <сек/мин>.\n"
        "⚠ Бот должен быть администратором в целевом канале."
    )


# ----------------------------------------------------------------------
# 1️⃣ Команды для настройки
# ----------------------------------------------------------------------
async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Задаём название канала, куда будем отправлять."""
    if not context.args:
        await update.message.reply_text("❗ Пример: /setchannel @mychannel")
        return
    # Сохраняем «чистый» идентификатор (можно и @username, и просто mychannel)
    channel_name = context.args[0].replace("@", "")
    context.chat_data["target_channel"] = channel_name
    await update.message.reply_text(f"✅ Целевой канал установлен: {channel_name}")


async def setdelay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Задаём задержку между сообщениями."""
    if not context.args:
        await update.message.reply_text("❗ Пример: /setdelay 5s  или  2m")
        return
    delay_sec = parse_delay(context.args[0])
    context.chat_data["delay_seconds"] = delay_sec
    await update.message.reply_text(f"✅ Задержка установлена: {delay_sec} сек.")


# ----------------------------------------------------------------------
# 2️⃣ Приём txt‑файла
# ----------------------------------------------------------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Пользователь присылает файл → сохраняем список username‑ов.
    Если уже есть «рабочий» процесс – игнорируем (можно добавить более сложную очередь).
    """
    user = update.effective_user
    document = update.message.document
    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❗ Пожалуйста, пришлите именно *.txt*‑файл.")
        return

    # Скачиваем файл во временную директорию
    file_path: Path = Path(tempfile.gettempdir()) / f"{user.id}_{document.file_id}.txt"
    await document.get_file().download_to_drive(custom_path=str(file_path))

    # Читаем строки, отбрасываем пустые и те, где есть пробелы в начале/конце
    with file_path.open(encoding="utf-8") as f:
        usernames = [line.strip() for line in f if line.strip()]

    if not usernames:
        await update.message.reply_text("⚠ В файле нет ни одного username‑а.")
        file_path.unlink(missing_ok=True)
        return

    # Сохраняем данные в контексте чата
    context.chat_data.update(
        {
            "queue": usernames,
            "index": 0,
            "delay": context.chat_data.get("delay_seconds", 1),
            "target_channel": context.chat_data.get("target_channel", None),
            "job": None,  # будет записан позже
        }
    )
    file_path.unlink(missing_ok=True)

    await update.message.reply_text(
        f"📥 Файл получен! Найдено {len(usernames)} никнеймов.\n"
        "✅ Чтобы начать рассылку, проверьте, что:\n"
        "   • /setchannel указан\n"
        "   • /setdelay указан\n"
        "   • Бот‑админ в целевом канале\n"
        "▶ Затем выполните /start_sending."
    )


# ----------------------------------------------------------------------
# 3️⃣ Старт рассылки
# ----------------------------------------------------------------------
async def start_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Запускает процесс отправки. Если уже запущен – предупреждаем.
    """
    data = context.chat_data
    if "queue" not in data or not data["queue"]:
        await update.message.reply_text("❗ Сначала пришлите txt‑файл с никнеймами.")
        return
    if not data.get("target_channel"):
        await update.message.reply_text("❗ Не указан целевой канал. Используйте /setchannel.")
        return
    if not data.get("delay"):
        await update.message.reply_text("❗ Не указана задержка. Используйте /setdelay.")
        return

    # Проверяем, что бот имеет право писать в канал
    try:
        await context.bot.get_chat(data["target_channel"])
    except Exception:
        await update.message.reply_text(
            "❗ Не удалось получить информацию о канале. Убедитесь, что я админ в нём."
        )
        return

    # Если уже есть запущенный job – завершаем его (чтобы не дублировать)
    if data.get("job"):
        data["job"].schedule_removal()

    # Сохраняем индекс текущей позиции
    data["index"] = 0

    # Планируем первое сообщение сразу (delay=0)
    async def job_callback():
        await send_next(update, context)

    # Запускаем «работу» через JobQueue
    job = context.job_queue.run_once(job_callback, when=0, name="sender_job")
    data["job"] = job

    await update.message.reply_text(
        f"▶ Рассылка началась. Первое сообщение будет через {data['delay']} сек."
    )


async def send_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Один «шаг» рассылки: отправляем текущий username, увеличиваем индекс,
    планируем следующую итерацию с учётом delay.
    """
    data = context.chat_data
    queue = data.get("queue", [])
    idx = data.get("index", 0)
    delay = data.get("delay", 1)
    channel = data.get("target_channel")

    if idx >= len(queue):
        # Всё отправлено – уведомляем и чистим состояние
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Все никнеймы отправлены! Ожидайте новый файл.",
        )
        # Очистка данных
        data.clear()
        if "job" in data:
            data.pop("job")
        return

    username = queue[idx]
    try:
        await context.bot.send_message(chat_id=channel, text=username)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Отправлен: {username}",
        )
    except Exception as e:
        # Ошибку логируем и продолжаем
        logger.exception("Ошибка отправки.")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⚠ Ошибка при отправке «{username}»: {e}",
        )

    # Переходим к следующему
    data["index"] = idx + 1
    # Планируем следующее сообщение через `delay` секунд
    data["job"] = context.job_queue.run_once(
        lambda: send_next(update, context), when=delay, name="sender_job"
    )


# ----------------------------------------------------------------------
# 4️⃣ Обработчики «запуска» и «остановки» (по желанию)
# ----------------------------------------------------------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена текущей рассылки."""
    data = context.chat_data
    if data.get("job"):
        data["job"].schedule_removal()
        data.pop("job")
    await update.message.reply_text("🛑 Рассылка отменена.")


# ----------------------------------------------------------------------
# 5️⃣_main_ – настройка Application и запуск
# ----------------------------------------------------------------------
def main() -> None:

    # ----> ВАШ ТОКЕН <----
    token = "8237086271:AAFOo4KN1Xpht9iQB9zlk2NKX3D1dq1NND0"

    # Создаём приложение (async)
    application = Application.builder().token(token).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setchannel", setchannel))
    application.add_handler(CommandHandler("setdelay", setdelay))
    application.add_handler(CommandHandler("start_sending", start_sending))
    application.add_handler(CommandHandler("cancel", cancel))

    # Любые документы (txt) обрабатываются нашим хендлером
    application.add_handler(MessageHandler(filters.Document.FileExtension('txt'), handle_document))

    # При желании можно добавить fallback‑handler для всех остальных сообщений
    application.add_handler(MessageHandler(filters.COMMAND, lambda u, c: None))  # игнорировать неизвестные команды

    # Запускаем «проживание» бота
    application.run_polling()
    logger.info("Бот запущен.")


if __name__ == "__main__":
    main()

