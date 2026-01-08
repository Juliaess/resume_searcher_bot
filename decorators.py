from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from auth import user_manager
import logging

logger = logging.getLogger(__name__)


def require_auth(func):
    """ Асинхронный декоратор для проверки авторизации """

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            if update is None or update.effective_user is None:
                return

            user_id = update.effective_user.id
            admin_contact = user_manager.get_admin_contact()

            can_request, message = await user_manager.can_make_request_async(user_id)
            logger.info(f"🔐 Проверка доступа для {user_id}: {can_request} - {message}")

            if not can_request:
                error_message = (
                    f"{message}\n\n"
                    f"🆔 Ваш ID: `{user_id}`\n\n"
                    f"📞 Для активации/продления доступа отправьте этот ID администратору:\n"
                    f"{admin_contact}"
                )
                if update.message:
                    await update.message.reply_text(message)
                return

            if (update.message and
                    not update.message.text.startswith(('/start', '/get_my_id', '/id')) and
                    context.user_data.get('current_search') == 'PDF поиск'):

                can_download, download_message = await user_manager.can_download_resume_async(user_id)
                if not can_download:
                    if update.message:
                        await update.message.reply_text(download_message)
                    return

            return await func(update, context, *args, **kwargs)

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в асинхронном декораторе require_auth: {e}", exc_info=True)
            if update and update.message:
                await update.message.reply_text("❌ Временная ошибка. Попробуйте позже.")
            return

    return wrapper


def require_admin(func):
    """ Декоратор для проверки прав администратора """

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            if update.callback_query:
                return await func(update, context, *args, **kwargs)

            if update is None or update.effective_user is None:
                return

            user_id = update.effective_user.id

            can_request, message = await user_manager.can_make_request_async(user_id)
            if not can_request:
                if update.message:
                    await update.message.reply_text(message)
                return

            if not user_manager.is_admin(user_id):
                if update.message:
                    await update.message.reply_text(f"⛔ Эта команда доступна только администраторам.")
                return

            return await func(update, context, *args, **kwargs)

        except Exception as e:
            logger.error(f"❌ Критическая ошибка в декораторе require_admin: {e}")
            if update and update.message:
                await update.message.reply_text("❌ Произошла внутренняя ошибка при проверке прав доступа.")
            return

    return wrapper


def handle_errors(func):
    """ Декоратор для обработки ошибок в функциях бота """

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"Ошибка в функции {func.__name__}: {e}", exc_info=True)
            if update and update.message:
                await update.message.reply_text("❌ Произошла непредвиденная ошибка\n\nПопробуйте позже или обратитесь к администратору.")
            return None

    return wrapper


def skip_for_callback_queries(func):
    """ Декоратор для пропуска обработки callback queries """

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update and update.callback_query:
            return
        return await func(update, context, *args, **kwargs)

    return wrapper