import os
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from auth import user_manager
import logging
from datetime import datetime
from decorators import require_admin
from pdf_indexer import pdf_indexer
from keyboards import get_main_keyboard, get_admin_keyboard, get_limits_keyboard, get_users_keyboard, get_database_keyboard, get_settings_keyboard, get_confirm_keyboard, get_logging_keyboard

logger = logging.getLogger(__name__)

AWAITING_LIMITS_INPUT = 1
AWAITING_DEACTIVATE_ID = 3
AWAITING_ACTIVATE_ID = 4
AWAITING_NEW_USER_DATA = 5
AWAITING_DELETE_ID = 6
AWAITING_UPDATE_INTERVAL = 11
AWAITING_LOGGING_LEVEL = 13
AWAITING_RESUME_UPLOAD = 15
AWAITING_NEW_ADMIN = 20
AWAITING_NEW_ADMIN_CONFIRM = 21
AWAITING_RESUMES_LIMIT = 22


@require_admin
async def change_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Панель смены администратора """
    current_user_id = update.effective_user.id
    current_user = user_manager.get_user(current_user_id)

    if not current_user or current_user['role'] != 'admin':
        await update.message.reply_text(
            "❌ Недостаточно прав!\n\n"
            "Только администратор может изменять права доступа."
        )
        return ConversationHandler.END

    users = user_manager.get_all_users()
    admin_users = [u for u in users if u['role'] == 'admin']

    message = (
        "👑 Смена администратора\n\n"
        f"📊 Текущие администраторы: {len(admin_users)}\n"
        f"🆔 Ваш ID: {current_user_id}\n\n"
        "⚠️ Внимание:\n"
        "• Вы потеряете права администратора после смены\n"
        "• Новый администратор получит полный доступ к боту\n"
        "• Убедитесь в правильности ID нового администратора\n\n"
        "Введите Telegram ID нового администратора:\n\n"
        "❌ 'отмена' - отменить операцию"
    )

    await update.message.reply_text(message)
    return AWAITING_NEW_ADMIN


@require_admin
async def handle_new_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода нового администратора """
    if update.message is None:
        return ConversationHandler.END

    current_user_id = update.effective_user.id
    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text(
            "❌ Смена администратора отменена.",
            reply_markup=get_admin_keyboard()
        )
        return ConversationHandler.END

    try:
        new_admin_id = int(text)

        if new_admin_id == current_user_id:
            await update.message.reply_text(
                "❌ Нельзя назначить самого себя!\n\n"
                "Вы уже являетесь администратором.\n"
                "Введите ID другого пользователя:"
            )
            return AWAITING_NEW_ADMIN

        current_user = user_manager.get_user(current_user_id)
        if not current_user or current_user['role'] != 'admin':
            await update.message.reply_text(
                "❌ Ошибка прав доступа!\n\n"
                "Недостаточно прав для выполнения операции."
            )
            return ConversationHandler.END

        new_user = user_manager.get_user(new_admin_id)

        if not new_user:
            await update.message.reply_text(
                f"❌ Пользователь не найден!\n\n"
                f"Пользователь с ID `{new_admin_id}` не зарегистрирован в системе.\n\n"
                f"💡 Решение:\n"
                f"1. Попросите пользователя запустить бота командой /start\n"
                f"2. Убедитесь, что ID правильный\n"
                f"3. Добавьте пользователя через панель администратора\n\n"
                f"Введите корректный ID или 'отмена':"
            )
            return AWAITING_NEW_ADMIN

        context.user_data['pending_admin_change'] = {
            'current_admin_id': current_user_id,
            'new_admin_id': new_admin_id,
            'new_admin_name': new_user['first_name'] or 'Неизвестно',
            'new_admin_username': new_user['username'] or 'Неизвестно'
        }

        await update.message.reply_text(
            f"⚠️ Подтверждение смены администратора\n\n"
            f"👑 Текущий администратор:\n"
            f"• ID: `{current_user_id}`\n"
            f"• Имя: {current_user['first_name'] or 'Неизвестно'}\n\n"
            f"🎯 Новый администратор:\n"
            f"• ID: `{new_admin_id}`\n"
            f"• Имя: {new_user['first_name'] or 'Неизвестно'}\n"
            f"• Username: @{new_user['username'] or 'не указан'}\n\n"
            f"🔒 После подтверждения:\n"
            f"• Вы потеряете права администратора\n"
            f"• Новый пользователь получит **полный доступ**\n"
            f"• Изменения **нельзя будет отменить**\n\n"
            f"Вы уверены, что хотите продолжить?",
            reply_markup=get_confirm_keyboard()
        )
        return AWAITING_NEW_ADMIN_CONFIRM

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID!\n\n"
            "ID должен состоять только из цифр.\n"
            "Введите корректный Telegram ID:"
        )
        return AWAITING_NEW_ADMIN


@require_admin
async def handle_admin_change_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка подтверждения смены администратора """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()
    pending_data = context.user_data.get('pending_admin_change', {})

    if not pending_data:
        await update.message.reply_text(
            "❌ Данные для смены администратора устарели.\n"
            "Начните процесс заново.",
            reply_markup=get_admin_keyboard()
        )
        return ConversationHandler.END

    current_admin_id = pending_data['current_admin_id']
    new_admin_id = pending_data['new_admin_id']

    if text == '✅ Подтвердить смену админа':
        try:
            current_user = user_manager.get_user(current_admin_id)
            if not current_user or current_user['role'] != 'admin':
                await update.message.reply_text(
                    "❌ Ошибка! Вы больше не являетесь администратором.",
                    reply_markup=get_admin_keyboard()
                )
                return ConversationHandler.END

            new_user = user_manager.get_user(new_admin_id)
            if not new_user:
                await update.message.reply_text(
                    f"❌ Ошибка! Пользователь с ID {new_admin_id} не найден.",
                    reply_markup=get_admin_keyboard()
                )
                return ConversationHandler.END

            user_manager.update_user_role(current_admin_id, 'recruiter')
            user_manager.update_user_role(new_admin_id, 'admin')

            logger.info(
                f"Администратор изменен: {current_admin_id} -> {new_admin_id} "
                f"({new_user['first_name']} @{new_user['username']})"
            )

            context.user_data.pop('pending_admin_change', None)

            await update.message.reply_text(
                f"✅ Администратор успешно изменен!\n\n"
                f"👑 Новый администратор:\n"
                f"• ID: `{new_admin_id}`\n"
                f"• Имя: {new_user['first_name'] or 'Неизвестно'}\n"
                f"• Username: @{new_user['username'] or 'не указан'}\n\n"
                f"⚡ Изменения вступят в силу сразу.\n"
                f"🔒 Вы теперь рекрутер.\n\n"
                f"Для доступа к админ-панели новый администратор должен перезапустить бота.",
                reply_markup=get_main_keyboard(update.effective_user.id)
            )

            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Ошибка при смене администратора: {e}")
            await update.message.reply_text(
                f"❌ Произошла ошибка при смене администратора: {str(e)}",
                reply_markup=get_admin_keyboard()
            )
            return ConversationHandler.END

    else:
        context.user_data.pop('pending_admin_change', None)
        await update.message.reply_text(
            "❌ Смена администратора отменена.",
            reply_markup=get_admin_keyboard()
        )
        return ConversationHandler.END


@require_admin
async def handle_resume_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка загруженных PDF резюме с автоматической индексацией """
    if update.message is None:
        return ConversationHandler.END

    if update.message.document:
        document = update.message.document
        if document.mime_type == 'application/pdf':
            file = await document.get_file()
            file_path = os.path.join('data/resumes/', document.file_name)

            if os.path.exists(file_path):
                await update.message.reply_text(
                    f"❌ Файл {document.file_name} уже существует на диске.\n\n"
                    f"💡 Рекомендации:\n"
                    f"• Переименуйте файл перед загрузкой\n"
                    f"• Удалите старый файл если нужно заменить"
                )
                return AWAITING_RESUME_UPLOAD

            await file.download_to_drive(file_path)

            try:
                success = pdf_indexer._index_single_pdf(document.file_name)
                if success:
                    await update.message.reply_text(
                        f"✅ Резюме {document.file_name} загружено и проиндексировано!\n"
                        f"💡 Файл доступен для поиска сразу"
                    )
                else:
                    await update.message.reply_text(
                        f"⚠️ Файл загружен, но не проиндексирован\n"
                        f"💡 Используйте /reindex для принудительной индексации"
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"⚠️ Файл загружен, ошибка индексации: {e}\n"
                    f"💡 Используйте /reindex для принудительной индексации"
                )
        else:
            await update.message.reply_text("❌ Пожалуйста, отправляйте только PDF файлы.")
    else:
        text = update.message.text.strip()
        if text.lower() in ['отмена', 'cancel']:
            await update.message.reply_text("❌ Загрузка резюме отменена.", reply_markup=get_admin_keyboard())
            return ConversationHandler.END
        else:
            await update.message.reply_text("📤 Отправьте PDF файлы резюме или введите 'отмена' для выхода.")

    return AWAITING_RESUME_UPLOAD


@require_admin
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Панель администратора """
    if update.message is None:
        return

    users = user_manager.get_all_users()
    active_users = [u for u in users if u['is_active']]
    total_requests_today = sum(u['requests_today'] for u in active_users)

    stats_text = (
        f"👥 Активных пользователей: {len(active_users)}\n"
        f"📊 Запросов сегодня: {total_requests_today}\n"
        f"🕒 Время сервера: {datetime.now().strftime('%H:%M %d.%m.%Y')}"
    )

    await update.message.reply_text(
        f"⚙️ Панель администратора\n\n{stats_text}\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )


@require_admin
async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Показать расширенный список пользователей """
    if update.message is None:
        return

    users = user_manager.get_all_users()

    if not users:
        await update.message.reply_text("📭 Список пользователей пуст.")
        return

    active_users = [u for u in users if u.get('status') == 'active']
    expired_users = [u for u in users if u.get('status') == 'expired']
    deactivated_users = [u for u in users if u.get('status') == 'deactivated']

    categories_keyboard = get_users_keyboard()
    text = update.message.text.strip()

    if text == '✅ Активные':
        await _show_active_users(update, active_users)
    elif text == '⏰ Истек срок':
        await _show_expired_users(update, expired_users)
    elif text == '❌ Деактивированные':
        await _show_deactivated_users(update, deactivated_users)
    else:
        await _show_users_overview(update, active_users, expired_users, deactivated_users, categories_keyboard)


async def _show_users_overview(update: Update, active_users: list, expired_users: list, deactivated_users: list, keyboard):
    """ Общий обзор пользователей """
    total_users = len(active_users) + len(expired_users) + len(deactivated_users)

    message = (
        "👥 Обзор пользователей\n\n"
        f"📊 Статистика по статусам:\n"
        f"• ✅ Активные: {len(active_users)}\n"
        f"• ⏰ Истек срок: {len(expired_users)}\n"
        f"• ❌ Деактивированные: {len(deactivated_users)}\n"
        f"• 📈 Всего в базе: {total_users}\n\n"

        "💡 Выберите категорию для просмотра:\n"
        "• Активные - текущие пользователи с доступом\n"
        "• Истек срок - доступ закончился, но могут запросить новый\n"
        "• Деактивированные - заблокированы администратором\n\n"

        "📋 Быстрые действия:\n"
        "• Используйте '➕ Добавить пользователя' для нового доступа\n"
        "• '🔓 Активировать пользователя' для восстановления доступа\n"
        "• '🗑️ Удалить пользователя' для полного удаления"
    )

    await update.message.reply_text(message, reply_markup=keyboard)


async def _show_active_users(update: Update, active_users: list):
    """ Показать активных пользователей """
    if not active_users:
        await update.message.reply_text("✅ Активные пользователи\n\nНет активных пользователей.")
        return

    message = "✅ Активные пользователи:\n\n"

    for i, user in enumerate(active_users, 1):
        role = "👑 Админ" if user['role'] == 'admin' else "👤 Рекрутер"
        days_left = f" ({user['days_remaining']}д.)" if user['days_remaining'] is not None else " (∞)"
        requests = f"{user['requests_today']}/{user['daily_requests_limit'] if user['daily_requests_limit'] > 0 else '∞'}"
        resumes = f"{user['resumes_today']}/{user['resumes_limit'] if user['resumes_limit'] > 0 else '∞'}"

        last_login = "никогда" if not user['last_login'] else datetime.fromisoformat(user['last_login']).strftime('%d.%m.%Y')

        message += (
            f"{i}. {user['display_name'] or 'Без имени'}\n"
            f"   🆔 ID: {user['telegram_id']} • @{user['username'] if user['username'] and user['username'].strip() else "нет"}\n"
            f"   {role} • 📊 Запросы: {requests} • 📄 Резюме: {resumes}{days_left}\n"
            f"   📅 Последний вход: {last_login}\n\n"
        )

    await update.message.reply_text(message)


async def _show_expired_users(update: Update, expired_users: list):
    """ Показать пользователей с истекшим сроком """
    if not expired_users:
        await update.message.reply_text(
            "⏰ Пользователи с истекшим сроком\n\nНет пользователей с истекшим сроком доступа.")
        return

    message = "⏰ Пользователи с истекшим сроком доступа:\n\n"
    message += "💡 Эти пользователи могут запросить продление доступа\n\n"

    for i, user in enumerate(expired_users, 1):
        role = "👑 Админ" if user['role'] == 'admin' else "👤 Рекрутер"
        requests_total = user['requests_today']
        resumes_total = user['resumes_total']
        last_login = "никогда" if not user['last_login'] else datetime.fromisoformat(user['last_login']).strftime(
            '%d.%m.%Y')
        created_date = datetime.fromisoformat(user['created_at']).strftime('%d.%m.%Y')

        message += (
            f"{i}. {user['display_name'] or 'Без имени'}\n"
            f"   🆔 ID: {user['telegram_id']} • @{user['username'] or 'нет'}\n"
            f"   {role} • 📅 Регистрация: {created_date}\n"
            f"   📊 Всего запросов: {requests_total} • 📄 Всего резюме: {resumes_total}\n"
            f"   📅 Последний вход: {last_login}\n\n"
        )

    await update.message.reply_text(message)


async def _show_deactivated_users(update: Update, deactivated_users: list):
    """ Показать деактивированных пользователей """
    if not deactivated_users:
        await update.message.reply_text("❌ Деактивированные пользователи\n\nНет деактивированных пользователей.")
        return

    message = "❌ Деактивированные пользователи:\n\n"
    message += "💡 Заблокированы администратором. Требуется ручная активация.\n\n"

    for i, user in enumerate(deactivated_users, 1):
        role = "👑 Админ" if user['role'] == 'admin' else "👤 Рекрутер"
        requests_total = user['requests_today']
        resumes_total = user['resumes_total']
        last_login = "никогда" if not user['last_login'] else datetime.fromisoformat(user['last_login']).strftime(
            '%d.%m.%Y')
        created_date = datetime.fromisoformat(user['created_at']).strftime('%d.%m.%Y')

        message += (
            f"{i}. {user['display_name'] or 'Без имени'}\n"
            f"   🆔 ID: {user['telegram_id']} • @{user['username'] or 'нет'}\n"
            f"   {role} • 📅 Регистрация: {created_date}\n"
            f"   📊 Всего запросов: {requests_total} • 📄 Всего резюме: {resumes_total}\n"
            f"   📅 Последний вход: {last_login}\n\n"
        )

    await update.message.reply_text(message)


@require_admin
async def show_users_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Панель управления пользователями """
    await update.message.reply_text(
        "👥 Управление пользователями\n\n"
        "Выберите действие:",
        reply_markup=get_users_keyboard()
    )


@require_admin
async def show_limits_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Панель управления лимитами """
    await update.message.reply_text(
        "📊 Управление лимитами пользователей\n\n"
        "Выберите тип лимита:",
        reply_markup=get_limits_keyboard()
    )


@require_admin
async def show_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Панель настроек системы """
    await update.message.reply_text(
        "⚙️ Настройки системы\n\n"
        "Доступные действия:\n"
        "• 🕐 Изменить интервал обновления - настройка автообновления\n"
        "• 📊 Логирование - уровень детализации логов\n\n"
        "Выберите действие:",
        reply_markup=get_settings_keyboard()
    )


@require_admin
async def show_database_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Панель управления PDF базой """
    await update.message.reply_text(
        "📁 Управление PDF базой\n\n"
        "Доступные действия:\n"
        "• 📤 Загрузка новых резюме - добавление PDF файлов\n"
        "• 🧹 Очистить кэш поиска - переиндексация PDF файлов\n\n"
        "Выберите действие:",
        reply_markup=get_database_keyboard()
    )


@require_admin
async def change_requests_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Изменение лимита запросов """
    context.user_data['current_operation_type'] = 'change_requests_limit'
    await update.message.reply_text(
        "🔢 Изменение лимита запросов\n\n"
        "Введите через пробел:\n"
        "• Telegram ID пользователя\n"
        "• Новый лимит запросов в день\n\n"
        "Пример: 123456789 50\n\n"
        "💡 Значения: 0 = безлимит, 10-1000 = ограничение\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_LIMITS_INPUT


@require_admin
async def change_resumes_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Изменение лимита резюме """
    context.user_data['current_operation_type'] = 'change_resumes_limit'
    await update.message.reply_text(
        "📄 Изменение лимита резюме\n\n"
        "Введите через пробел:\n"
        "• Telegram ID пользователя\n"
        "• Новый лимит резюме в день\n\n"
        "Пример: 123456789 20\n\n"
        "💡 Значения: 0 = безлимит, 1-1000 = ограничение\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_RESUMES_LIMIT


@require_admin
async def handle_resumes_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода лимита резюме """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Операция отменена.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Неверный формат")

        user_id = int(parts[0])
        resumes_limit = int(parts[1])

        if resumes_limit < 0:
            await update.message.reply_text("❌ Лимит резюме не может быть отрицательным.")
            return AWAITING_RESUMES_LIMIT

        user = user_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден.")
            return AWAITING_RESUMES_LIMIT

        if user_manager.update_resumes_limit(user_id, resumes_limit):
            if resumes_limit == 0:
                message = f"✅ Лимит резюме для пользователя {user_id} установлен: безлимит"
            else:
                message = f"✅ Лимит резюме для пользователя {user_id} установлен: {resumes_limit} в день"

            await update.message.reply_text(message, reply_markup=get_admin_keyboard())
        else:
            await update.message.reply_text("❌ Ошибка при обновлении лимита резюме.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите два числа через пробел:")
        return AWAITING_RESUMES_LIMIT


@require_admin
async def change_access_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Изменение срока доступа """
    context.user_data['current_operation_type'] = 'change_access_days'
    await update.message.reply_text(
        "📅 Изменение срока доступа\n\n"
        "Введите через пробел:\n"
        "• Telegram ID пользователя\n"
        "• Количество дней доступа\n\n"
        "Пример: 123456789 30\n\n"
        "💡 Значения: 0 = бессрочный доступ, 1-365 = ограничение\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_LIMITS_INPUT


@require_admin
async def handle_limits_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода лимитов с явным указанием типа операции """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Операция отменена.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("Неверный формат")

        user_id = int(parts[0])
        value = int(parts[1])

        user = user_manager.get_user(user_id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден.")
            return AWAITING_LIMITS_INPUT

        operation_type = context.user_data.get('current_operation_type')

        if operation_type == 'change_requests_limit':
            if value < 0:
                await update.message.reply_text("❌ Лимит запросов не может быть отрицательным.")
                return AWAITING_LIMITS_INPUT

            user_manager.update_user_limits(user_id, daily_requests_limit=value)
            if value == 0:
                message = f"✅ Лимит запросов для пользователя {user_id} установлен: безлимит"
            else:
                message = f"✅ Лимит запросов для пользователя {user_id} установлен: {value} в день"

        elif operation_type == 'change_access_days':
            if value < 0:
                await update.message.reply_text("❌ Срок доступа не может быть отрицательным.")
                return AWAITING_LIMITS_INPUT

            user_manager.update_user_limits(user_id, access_days=value)
            if value == 0:
                message = f"✅ Срок доступа для пользователя {user_id} установлен: бессрочный"
            else:
                message = f"✅ Срок доступа для пользователя {user_id} установлен: {value} дней"

        if 'current_operation_type' in context.user_data:
            del context.user_data['current_operation_type']

        await update.message.reply_text(message, reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    except ValueError as e:
        await update.message.reply_text("❌ Неверный формат. Введите два числа через пробел:")
        return AWAITING_LIMITS_INPUT


@require_admin
async def reset_counters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Сброс счетчиков запросов """
    users = user_manager.get_all_users()
    reset_count = 0

    for user in users:
        if user_manager.reset_daily_requests(user['telegram_id']):
            reset_count += 1

    await update.message.reply_text(
        f"🔄 Сброшены счетчики запросов для {reset_count} пользователей",
        reply_markup=get_admin_keyboard()
    )


@require_admin
async def clear_search_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Очистка кэша поиска """
    try:
        pdf_indexer.clear_cache()
        await update.message.reply_text(
            "🧹 Кэш поиска очищен!\n\n"
            "Все PDF файлы будут перечитаны при следующем поиске.",
            reply_markup=get_database_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка очистки кэша: {e}")
        await update.message.reply_text(
            f"❌ Ошибка очистки кэша: {str(e)}",
            reply_markup=get_database_keyboard()
        )


@require_admin
async def show_system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Расширенная статистика системы """
    users = user_manager.get_all_users()

    active_users = [u for u in users if u.get('status') == 'active']
    expired_users = [u for u in users if u.get('status') == 'expired']
    deactivated_users = [u for u in users if u.get('status') == 'deactivated']

    total_requests_today = sum(u.get('requests_today', 0) for u in users)
    total_resumes_today = sum(u.get('resumes_today', 0) for u in users)
    total_resumes_month = sum(u.get('resumes_this_month', 0) for u in users)
    total_resumes_all = sum(u.get('resumes_total', 0) for u in users)

    limited_users = [u for u in active_users if u.get('daily_requests_limit', 0) > 0]
    unlimited_users = [u for u in active_users if u.get('daily_requests_limit', 0) == 0]

    message = (
        "📈 Расширенная статистика системы\n\n"
        f"👥 Пользователи:\n"
        f"• ✅ Активные: {len(active_users)}\n"
        f"• ⏰ Истек срок: {len(expired_users)}\n"
        f"• ❌ Деактивированные: {len(deactivated_users)}\n"
        f"• 📊 Всего в базе: {len(users)}\n\n"

        f"📊 Активность за сегодня:\n"
        f"• Запросы: {total_requests_today}\n"
        f"• Резюме: {total_resumes_today}\n\n"

        f"📈 Резюме за все время:\n"
        f"• За месяц: {total_resumes_month}\n"
        f"• Всего: {total_resumes_all}\n\n"

        f"🎯 Лимиты: {len(limited_users)} с лимитом, {len(unlimited_users)} безлимитных\n\n"

        f"🕒 Время сервера: {datetime.now().strftime('%H:%M %d.%m.%Y')}\n\n"
    )

    if active_users:
        message += "🏆 Топ активных пользователей сегодня:\n"
        active_users_sorted = sorted(active_users, key=lambda x: x.get('resumes_today', 0), reverse=True)

        for i, user in enumerate(active_users_sorted, 1):
            resumes = user.get('resumes_today', 0)
            requests = user.get('requests_today', 0)
            user_name = user.get('username', 'Без имени')
            message += f"{i}. @{user_name} - {requests} запросов, {resumes} резюме\n"

        message += "\n"
    else:
        message += "ℹ️ Нет активных пользователей\n\n"

    if active_users:
        message += "📋 Детальная статистика пользователей:\n"

        for user in active_users[:8]:
            days_left = f" ({user.get('days_remaining', 0)}д.)" if user.get('days_remaining') is not None else ""
            limit_display = user.get('daily_requests_limit', 0) if user.get('daily_requests_limit', 0) > 0 else '∞'
            resumes_limit_display = user.get('resumes_limit', 0) if user.get('resumes_limit', 0) > 0 else '∞'
            user_name = user.get('username', 'Без имени')

            message += (
                f"• @{user_name} - "
                f"Запросы: {user.get('requests_today', 0)}/{limit_display} | "
                f"Резюме: {user.get('resumes_today', 0)}/{resumes_limit_display}{days_left}\n"
            )

    if len(message) > 4000:
        message = message[:3900] + "\n\n⚠️ Сообщение сокращено из-за ограничения длины"

    await update.message.reply_text(message)


@require_admin
async def add_user_with_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Добавление пользователя с настройками лимитов """
    await update.message.reply_text(
         "➕ Добавление нового пользователя с настройками\n\n"
        "Введите данные в формате:\n"
        "`ID ЛимитЗапросов ДниДоступа ЛимитРезюмеДень`\n\n"
        "Пример: 123456789 50 30 20\n\n"
        "💡 Пояснения:\n"
        "• ID - Telegram ID пользователя\n"
        "• ЛимитЗапросов - запросов в день (0 = безлимит)\n"
        "• ДниДоступа - срок действия доступа (0 = бессрочно)\n"
        "• Лимит резюме в день (0 = безлимит)\n\n"
        "❌ 'отмена' - отменить добавление"
    )
    return AWAITING_NEW_USER_DATA


@require_admin
async def handle_new_user_with_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода данных нового пользователя """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Добавление пользователя отменено.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        parts = text.split()
        if len(parts) != 4:
            raise ValueError("Неверный формат")

        telegram_id = int(parts[0])
        daily_limit = int(parts[1])
        access_days = int(parts[2])
        resumes_limit = int(parts[3])

        if daily_limit < 0 or access_days < 0:
            await update.message.reply_text("❌ Лимиты не могут быть отрицательными.")
            return AWAITING_NEW_USER_DATA

        existing_user = user_manager.get_user(telegram_id)
        if existing_user:
            user_manager.activate_user(telegram_id, access_days)
            user_manager.update_user_limits(telegram_id, daily_requests_limit=daily_limit)
            user_manager.update_resumes_limit(telegram_id, resumes_limit)

            limit_text = "безлимит" if daily_limit == 0 else f"{daily_limit} в день"
            access_text = "бессрочно" if access_days == 0 else f"{access_days} дней"
            resumes_text = "безлимит" if resumes_limit == 0 else f"{resumes_limit} в день"

            await update.message.reply_text(
                 f"✅ Существующий пользователь ОБНОВЛЕН и АКТИВИРОВАН!\n\n"
                f"• 🆔 ID: {telegram_id}\n"
                f"• 📊 Лимит запросов: {limit_text}\n"
                f"• ⏰ Срок доступа: {access_text}\n"
                f"• 📄 Лимит резюме: {resumes_text}\n\n"
                f"Пользователь снова может использовать бота.",
                reply_markup=get_admin_keyboard()
            )
        else:
            if user_manager.add_user_by_admin(
                telegram_id=telegram_id,
                daily_requests_limit=daily_limit,
                access_days=access_days,
                resumes_limit=resumes_limit
            ):
                limit_text = "безлимит" if daily_limit == 0 else f"{daily_limit} в день"
                access_text = "бессрочно" if access_days == 0 else f"{access_days} дней"
                resumes_text = "безлимит" if resumes_limit == 0 else f"{resumes_limit} в день"

                await update.message.reply_text(
                    f"✅ Пользователь добавлен!\n\n"
                    f"• 🆔 ID: {telegram_id}\n"
                    f"• 📊 Лимит запросов: {limit_text}\n"
                    f"• ⏰ Срок доступа: {access_text}\n"
                    f"• 📄 Лимит резюме: {resumes_text}\n\n"
                    f"Пользователь может теперь использовать бота.",
                    reply_markup=get_admin_keyboard()
                )
            else:
                await update.message.reply_text("❌ Ошибка при добавлении пользователя.")
                return AWAITING_NEW_USER_DATA
        return ConversationHandler.END
    except ValueError as e:
        await update.message.reply_text("❌ Неверный формат. Введите три числа через пробел:")
        return AWAITING_NEW_USER_DATA


@require_admin
async def deactivate_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Деактивация пользователя """
    await update.message.reply_text(
        "🔒 Деактивация пользователя\n\n"
        "Введите Telegram ID пользователя для деактивации:\n\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_DEACTIVATE_ID


@require_admin
async def handle_deactivate_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода ID для деактивации """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Деактивация отменена.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        user_id = int(text)

        if user_manager.deactivate_user(user_id):
            await update.message.reply_text(
                f"✅ Пользователь {user_id} деактивирован!\n\n"
                f"Доступ к боту заблокирован.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Ошибка при деактивации пользователя.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите число:")
        return AWAITING_DEACTIVATE_ID


@require_admin
async def activate_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Активация пользователя """
    await update.message.reply_text(
        "🔓 Активация пользователя\n\n"
        "Введите Telegram ID пользователя для активации:\n\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_ACTIVATE_ID


@require_admin
async def handle_activate_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода ID для активации """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Активация отменена.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        user_id = int(text)

        if user_manager.activate_user(user_id):
            await update.message.reply_text(
                f"✅ Пользователь {user_id} активирован!\n\n"
                f"Доступ к боту восстановлен.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Ошибка при активации пользователя.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите число:")
        return AWAITING_ACTIVATE_ID


@require_admin
async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Удаление пользователя из базы данных """
    await update.message.reply_text(
        "🗑️ Удаление пользователя\n\n"
        "Введите Telegram ID пользователя для удаления:\n\n"
        "⚠️ Внимание: Это действие нельзя отменить!\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_DELETE_ID


@require_admin
async def handle_delete_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода ID для удаления """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Удаление отменено.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        user_id = int(text)
        user = user_manager.get_user(user_id)

        if not user:
            await update.message.reply_text("❌ Пользователь не найден.")
            return AWAITING_DELETE_ID

        success = user_manager.delete_user(user_id)

        if success:
            await update.message.reply_text(
                f"✅ Пользователь {user_id} удален из базы данных!\n\n"
                f"Все данные пользователя были полностью удалены.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Ошибка при удалении пользователя.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите число:")
        return AWAITING_DELETE_ID


@require_admin
async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Отмена текущей операции """
    if 'current_operation_type' in context.user_data:
        del context.user_data['current_operation_type']
    await update.message.reply_text(
        "❌ Операция отменена.",
        reply_markup=get_admin_keyboard()
    )
    return ConversationHandler.END


@require_admin
async def change_update_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Изменение интервала обновления базы """
    current_interval = user_manager.get_system_setting('db_refresh_interval', '3600')
    await update.message.reply_text(
        f"🕐 Изменение интервала обновления базы\n\n"
        f"📊 Текущий интервал: {int(current_interval) // 3600} часов\n\n"
        "Введите новый интервал в часах (1-24):\n\n"
        "💡 Рекомендации:\n"
        "• 1-2 часа - для активного поиска\n"
        "• 4-6 часов - для обычной работы\n"
        "• 12-24 часа - для экономии ресурсов\n\n"
        "❌ 'отмена' - отменить операцию"
    )
    return AWAITING_UPDATE_INTERVAL


@require_admin
async def change_logging(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Настройка логирования """
    current_level = user_manager.get_system_setting('logging_level', 'INFO')

    await update.message.reply_text(
        f"📊 Настройка логирования\n\n"
        f"📝 Текущий уровень: {current_level}\n\n"
        "Выберите уровень логирования:\n\n"
        "• 🔍 DEBUG - максимальная детализация\n"
        "• ℹ️ INFO - основная информация\n"
        "• ⚠️ WARNING - только предупреждения\n"
        "• ❌ ERROR - только ошибки\n\n"
        "❌ 'отмена' - отменить операцию",
        reply_markup=get_logging_keyboard()
    )
    return AWAITING_LOGGING_LEVEL


@require_admin
async def upload_resumes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Загрузка новых резюме """
    await update.message.reply_text(
        "📤 Загрузка новых резюме\n\n"
        "Отправьте PDF файлы резюме. Бот сохранит их в папку с резюме.\n"
        "После загрузки не забудьте обновить базу кандидатов.\n\n"
        "❌ 'отмена' - завершить загрузку"
    )
    return AWAITING_RESUME_UPLOAD


@require_admin
async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Отмена загрузки резюме """
    await update.message.reply_text(
        "❌ Загрузка резюме отменена.",
        reply_markup=get_admin_keyboard()
    )
    return ConversationHandler.END


@require_admin
async def handle_update_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка ввода нового интервала обновления """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel']:
        await update.message.reply_text("❌ Операция отменена.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    try:
        hours = int(text)
        if hours < 1 or hours > 24:
            raise ValueError("Интервал должен быть от 1 до 24 часов")

        seconds = hours * 3600

        if user_manager.save_system_setting('db_refresh_interval', str(seconds)):
            await update.message.reply_text(
                f"✅ Интервал обновления изменен!\n\n"
                f"🕐 Новый интервал: {hours} часов\n"
                f"⏰ В секундах: {seconds} сек.\n\n"
                f"База будет обновляться автоматически.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Ошибка при сохранении интервала.")

    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите число от 1 до 24:")
        return AWAITING_UPDATE_INTERVAL

    return ConversationHandler.END


@require_admin
async def handle_logging_level_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Обработка выбора уровня логирования """
    if update.message is None:
        return ConversationHandler.END

    text = update.message.text.strip()

    if text.lower() in ['отмена', 'cancel'] or text == '⬅️ Назад в админку':
        await update.message.reply_text("❌ Операция отменена.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    level_map = {
        '🔍 DEBUG': 'DEBUG',
        'ℹ️ INFO': 'INFO',
        '⚠️ WARNING': 'WARNING',
        '❌ ERROR': 'ERROR'
    }

    if text in level_map:
        level = level_map[text]

        if user_manager.save_system_setting('logging_level', level):
            numeric_level = getattr(logging, level.upper(), None)
            if isinstance(numeric_level, int):
                logging.getLogger().setLevel(numeric_level)

            await update.message.reply_text(
                f"✅ Уровень логирования изменен!\n\n"
                f"📊 Новый уровень: {level}\n"
                f"🔧 Применен для всех модулей.\n\n"
                f"Изменения вступят в силу немедленно.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Ошибка при изменении уровня логирования.")
    else:
        await update.message.reply_text("❌ Неверный выбор уровня.")
        return AWAITING_LOGGING_LEVEL

    return ConversationHandler.END