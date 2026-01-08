import os
import logging
import asyncio
import re
import time
from typing import Optional
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import TimedOut
from pdf_indexer import pdf_indexer
from config import RESUMES_FOLDER
from auth import user_manager
from datetime import datetime
from decorators import require_auth
from keyboards import get_main_keyboard

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Обработчик команды /start """
    if update.message is None:
        return

    user = update.effective_user
    user_id = user.id
    admin_contact = user_manager.get_admin_contact()

    user_manager.add_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    user_manager.update_user_info(
        telegram_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or ""
    )
    user_info = user_manager.get_user(user.id)
    can_request, access_message = await user_manager.can_make_request_async(user_id)
    logger.info(f"🔐 Проверка доступа для {user_id}: {can_request} - {access_message}")
    if not can_request:
        deactivation_message = (
            f"👋 Добро пожаловать, {user.first_name or 'пользователь'}!\n\n"
            f"✅ Вы успешно зарегистрированы в системе!\n"
            f"🆔 Ваш ID: `{user_id}`\n\n"
            f"📩 Отправьте ID администратору, чтобы получить доступ:\n"
            f"{admin_contact}\n\n"
            f"После активации перезапустите бота командой /start"
        )
        await update.message.reply_text(deactivation_message)
        return
    else:
        increment_result = await user_manager.increment_request_count_async(user_id)
        if increment_result:
            logger.info(f"📊 Увеличен счетчик запросов для {user_id}")
        else:
            logger.error(f"❌ Ошибка увеличения счетчика запросов для {user_id}")
        await user_manager.update_last_login_async(user_id)

    role_text = "👑 Администратор" if user_info['role'] == 'admin' else "👤 Рекрутер"
    status_text = "✅ Активен" if user_info['is_active'] else "❌ Деактивирован"
    welcome_text = (
        f"👋 Добро пожаловать, {user.first_name or 'пользователь'}!\n\n"
        f"🔐 {role_text}\n"
        f"{status_text}\n\n"
    )
    if user_info['role'] == 'admin':
        welcome_text += (
            "⚙️ Панель управления - управление пользователями\n\n"
            "🔍 Для поиска резюме просто отправьте текст из опыта работы кандидата\n\n"
            "💡 Совет: Используйте уникальные фразы из опыта работы для точного поиска\n\n"
            "Команды:\n"
            "/get_my_id - полная информация о пользователе.\n"
            "/id - быстрое получение id.\n\n"
            "/refresh_users - обновление данных пользователей\n\n"
            "/index_status - статус индексации"
        )
    else:
        welcome_text += (
            "🔍 Для поиска резюме просто отправьте текст из опыта работы кандидата\n\n"
            "💡 Советы для точного поиска:\n"
            "• Копируйте конкретные обязанности с предыдущих мест работы\n"
            "• Добавьте названия компаний и проектов\n"
            "• Включите уникальные достижения и результаты\n"
            "• Используйте текст из раздела 'Опыт работы'\n\n"
            f"📞 Контакт администратора: {admin_contact}\n\n"
            "Команды:\n"
            "/get_my_id - полная информация о пользователе\n"
            "/id - быстрое получение id."
        )
    keyboard = get_main_keyboard(user.id)
    await update.message.reply_text(welcome_text, reply_markup=keyboard)


async def check_index_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Проверка статуса индекса """
    if update.message is None:
        return

    user_id = update.effective_user.id
    if not user_manager.is_admin(user_id):
        await update.message.reply_text("❌ Только для администраторов")
        return

    try:
        stats = pdf_indexer.get_index_stats()
        pdf_files = [f for f in os.listdir(RESUMES_FOLDER) if f.lower().endswith('.pdf')]
        missing_count = pdf_indexer.cleanup_missing_files()

        await update.message.reply_text(
            f"📊 Статус индексации\n\n"
            f"📁 Файлов в папке: {len(pdf_files)}\n"
            f"📄 В индексе: {stats['total_indexed_files']}\n"
            f"💾 Размер базы: {stats['db_size_mb']:.1f} MB\n"
            f"🧹 Очищено отсутствующих: {missing_count}\n\n"
            f"🔍 Неиндексированные файлы: {max(0, len(pdf_files) - stats['total_indexed_files'])}"
        )

    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def quick_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Быстрая команда для получения ID """
    if update.message is None:
        return
    user = update.effective_user
    admin_contact = user_manager.get_admin_contact()
    await update.message.reply_text(
        f"🆔 Ваш Telegram ID: `{user.id}`\n\n"
        f"📋 Скопируйте ID и отправьте администратору {admin_contact} для получения доступа.\n\n"
        f"💡 Для полной информации используйте команду /get_my_id"
    )


@require_auth
async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Команда для получения информации о пользователе """
    if update.message is None:
        return

    user = update.effective_user
    user_id = user.id

    user_manager.update_user_info(
        telegram_id=user_id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or ""
    )

    user_manager.force_monthly_reset_check(user_id)
    user_info = user_manager.get_user(user_id)

    if not user_info:
        user_manager.add_user_by_admin(
            telegram_id=user_id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or ""
        )
        user_info = user_manager.get_user(user_id)

    resume_stats = user_manager.get_resume_stats(user_id)

    role_emoji = "👑" if user_info.get('role') == 'admin' else "👤"
    role_text = "Администратор" if user_info.get('role') == 'admin' else "Рекрутер"
    status_emoji = "✅" if user_info.get('is_active') else "❌"
    status_text = "Активен" if user_info.get('is_active') else "Неактивен"
    limit_text = "∞" if user_info.get('daily_requests_limit') == 0 else str(user_info.get('daily_requests_limit', 0))
    requests_info = f"{user_info.get('requests_today', 0)}/{limit_text}"

    if user_info['access_expires']:
        try:
            expires_date = datetime.fromisoformat(user_info['access_expires'])
            days_remaining = (expires_date - datetime.now()).days
            access_text = f"{days_remaining} дней" if days_remaining > 0 else "Истёк"
        except ValueError:
            access_text = "Ошибка даты"
    else:
        access_text = "Бессрочный"

    admin_contact = user_manager.get_admin_contact()
    resumes_limit_text = "∞" if resume_stats['resumes_limit'] == 0 else str(resume_stats['resumes_limit'])
    resumes_info = f"{resume_stats['resumes_today']}/{resumes_limit_text}"

    message = (
        f"👤 Ваша учетная запись\n\n"
        f"📋 Основная информация:\n"
        f"• 🆔 Telegram ID: {user_id}\n"
        f"• 👤 Имя: {user.first_name or 'Не указано'}\n"
        f"• 📛 Фамилия: {user.last_name or 'Не указана'}\n"
        f"• 💎 Username: {f'@{user.username}' if user.username else 'Не указан'}\n\n"
        f"⚙️ Статус и права:\n"
        f"• {role_emoji} Роль: {role_text}\n"
        f"• {status_emoji} Статус: {status_text}\n"
        f"• 📊 Запросы сегодня: {requests_info}\n"
        f"• ⏰ Доступ: {access_text}\n\n"
        f"📊 Статистика резюме:\n"
        f"• 📅 Сегодня: {resume_stats['resumes_today']}/{resumes_limit_text}\n"
        f"• 📈 Этот месяц: {resume_stats['resumes_this_month']}/{resumes_limit_text}\n"
        f"• 🏆 Всего: {resume_stats['resumes_total']}\n\n"
    )
    if user_info['role'] == 'recruiter':
        if not user_info['is_active']:
            message += (
                f"❌ Ваш аккаунт деактивирован\n\n"
                f"📞 Для активации обратитесь к администратору:\n"
                f"{admin_contact}\n\n"
            )
        elif user_info['access_expires'] and days_remaining <= 0:
            message += (
                f"⏰ Срок доступа истек\n\n"
                f"📞 Для продления обратитесь к администратору:\n"
                f"{admin_contact}\n\n"
            )
        else:
            message += (
                f"💡 Вы можете:\n"
                f"• 🔍 Искать резюме по тексту опыта работы\n"
                f"• 📊 Использовать до {limit_text} запросов в день\n"
                f"• ⏰ Работать ещё: `{access_text}`\n\n"
            )
    if user_info['role'] == 'admin':
        message += (
            f"💡 Как администратор вы можете:\n"
            f"• ⚙️ Управлять пользователями\n"
            f"• 📊 Настраивать лимиты\n"
            f"• 📁 Загружать резюме\n"
            f"• 📈 Просматривать статистику\n\n"
        )

    if not user_info['is_active'] or (user_info['access_expires'] and days_remaining <= 0):
        message += (
            f"📝 Инструкция по получению доступа:\n"
            f"1. Скопируйте ваш ID: `{user_id}`\n"
            f"2. Отправьте ID администратору\n"
            f"3. Дождитесь активации аккаунта\n"
            f"4. Перезапустите бота командой /start\n\n"
        )
    else:
        message += (
            f"🆘 Если возникли проблемы 🆘\n"
            f"📞 Контакт администратора\n"
            f"{admin_contact}\n\n"
        )

    keyboard = []
    if user_info['role'] == 'admin':
        keyboard.append(['⚙️ Панель управления'])
    keyboard.append(['🔄 Обновить информацию'])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(message, reply_markup=reply_markup)


@require_auth
async def handle_pdf_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Быстрый поиск через индексную базу """
    if update.message is None:
        return

    user_id = update.effective_user.id
    await user_manager.update_last_login_async(user_id)

    user_message = update.message.text.strip()
    start_time = time.time()

    if user_message.lower() in ['отмена', 'cancel', 'стоп', 'stop', 'выход']:
        await update.message.reply_text("Поиск отменен.", reply_markup=get_main_keyboard(update.effective_user.id))
        return

    if not user_message or len(user_message) < 30:
        await update.message.reply_text(
            "❌ Текст для поиска слишком короткий. Нужно минимум 30 символов уникального текста.\n\n"
            "💡 Совет: Скопируйте больше текста из раздела 'Опыт работы' или 'О себе'"
        )
        return

    if is_too_generic(user_message):
        await update.message.reply_text(
            "❌ Текст содержит слишком общие фразы\n\n"
            "💡 Советы для точного поиска:\n"
            "• Копируйте конкретные обязанности с предыдущих мест работы\n"
            "• Добавьте названия компаний и проектов\n"
            "• Включите уникальные достижения и результаты\n"
            "• Используйте текст из раздела 'Опыт работы'\n\n"
            "🔍 Попробуйте ввести более уникальный текст ниже"
        )
        return

    search_message = await update.message.reply_text(
        f"🔍 Идет быстрый поиск по базе резюме..."
    )

    try:
        search_results = pdf_indexer.search_indexed_pdf(user_message, limit=5)

        logger.info(f"🔍 ИНДЕКСНЫЙ ПОИСК: '{user_message[:50]}...' - найдено: {len(search_results)}")
        search_duration = time.time() - start_time
        logger.info(f"🔍 Поиск '{user_message[:50]}...' занял {search_duration:.2f}сек, найдено: {len(search_results)}")

        if not search_results:
            await search_message.edit_text(
                "❌ Точных совпадений не найдено\n\n"
                "💡 Рекомендации:\n"
                "• Проверьте текст на опечатки\n"
                "• Используйте более уникальные фразы из опыта работы\n"
                "• Добавьте названия компаний/проектов\n"
                "• Скопируйте текст из конкретных обязанностей\n\n"
                "Попробуйте другой текст для поиска:"
            )
            return

        best_result = search_results[0]

        await search_message.edit_text(
            f"✅ Резюме найдено.\n\n"
            f"👤 {best_result['candidate_name']}\n"
            f"📊 Релевантность текста: {best_result.get('relevance_score', 0):.1%}\n\n"
        )

        success = await safe_send_pdf(update, best_result['file_path'], "", os.path.basename(best_result['file_path']))

        if success:
            if len(search_results) > 1:
                other_results = search_results[1:3]

                if other_results:
                    keyboard = [
                        [InlineKeyboardButton(f"🔍 Показать ещё {len(other_results)} варианта", callback_data="show_other_results")],
                        [InlineKeyboardButton("✅ Завершить поиск", callback_data="finish_search")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await update.message.reply_text(
                        f"💡 Найдено {len(other_results)} дополнительных релевантных резюме",
                        reply_markup=reply_markup
                    )
                    context.user_data['other_search_results'] = other_results
                else:
                    await update.message.reply_text(
                        "🔻Для поиска следующего кандидата отправьте текст из резюме.",
                        reply_markup=get_main_keyboard(update.effective_user.id)
                    )
            else:
                await update.message.reply_text(
                    "🔻Для поиска следующего кандидата отправьте текст из резюме.",
                    reply_markup=get_main_keyboard(update.effective_user.id)
                )
        else:
            await update.message.reply_text(
                "❌ Отмена отправки pdf файла",
                reply_markup=get_main_keyboard(update.effective_user.id)
            )
    except Exception as e:
        logger.error(f"❌ Ошибка при поиске PDF: {e}")
        await search_message.edit_text(
            "❌ Произошла ошибка при поиске. Попробуйте позже или обратитесь к администратору."
        )


def is_too_generic(text: str) -> bool:
    """ Умная проверка на общие фразы """
    text_lower = text.lower().strip()

    if len(text) > 300:
        logger.info("✅ Длинный текст - пропускаем проверку")
        return False

    forbidden_patterns = [
        r'^[\s\S]*(резюме обновлено|желательное время в пути)[\s\S]*$',
        r'^[\s\S]*(занятость|график работы|специализации:)[\s\S]{0,100}$',
    ]
    for pattern in forbidden_patterns:
        if re.match(pattern, text_lower):
            logger.info("❌ Текст соответствует запрещенному паттерну")
            return True
    unique_indicators = [
        r'ооо\s+\w+', r'зао\s+\w+', r'ао\s+\w+',
        r'руководство\s+отделом', r'подбор\s+персонала', r'ведение\s+отчетности',
        r'формирование\s+бюджета', r'мониторинг\s+рынка', r'адаптация\s+сотрудников',
        r'\d+\s+человек', r'\d+\s+месяц', r'\d+\s+год',
        'фортренд', 'эстетик лайн', 'call-центр', 'массовый подбор'
    ]
    unique_count = 0
    for indicator in unique_indicators:
        if re.search(indicator, text_lower, re.IGNORECASE):
            unique_count += 1
    if unique_count >= 2:
        logger.info(f"✅ Текст содержит {unique_count} уникальных индикаторов")
        return False
    logger.info("❌ Текст не содержит достаточного количества уникального контента")
    return True


@require_auth
async def handle_pdf_search_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Обработчик решений для PDF поиска """
    try:
        if update.callback_query is None:
            return

        query = update.callback_query
        await query.answer()

        if query.message is None:
            return

        action = query.data
        if action == "show_other_results":
            other_results = context.user_data.get('other_search_results', [])

            if other_results:
                sent_count = 0
                for result in other_results:
                    try:
                        success = await safe_send_pdf(
                            update,
                            result['file_path'],
                            f"📄 Дополнительное резюме\n"
                            f"👤 Кандидат: {result['candidate_name']}",
                            os.path.basename(result['file_path'])
                        )
                        if success:
                            sent_count += 1
                            await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки дополнительного PDF: {e}")
                await query.message.reply_text(
                    f"✅ Отправлено {sent_count} дополнительных резюме",
                    reply_markup=get_main_keyboard(update.effective_user.id)
                )
            else:
                await query.message.reply_text(
                    "❌ Дополнительные результаты не найдены",
                    reply_markup=get_main_keyboard(update.effective_user.id)
                )
        elif action == "finish_search":
            await query.edit_message_text(
                "✅ Поиск завершен\n"
                "🔻Для поиска следующего кандидата отправьте текст из резюме.",
                reply_markup=get_main_keyboard(update.effective_user.id)
            )
        context.user_data.pop('other_search_results', None)

    except Exception as e:
        logger.error(f"❌ Ошибка в handle_pdf_search_decision: {e}")


@require_auth
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Асинхронный обработчик обычных текстовых сообщений """
    if update.message is None:
        return

    user_message = update.message.text.strip()
    user_id = update.effective_user.id
    admin_contact = user_manager.get_admin_contact()

    admin_states = [
        'AWAITING_DELETE_ID', 'AWAITING_LIMITS_INPUT', 'AWAITING_UNLIMITED_INPUT',
        'AWAITING_DEACTIVATE_ID', 'AWAITING_ACTIVATE_ID', 'AWAITING_NEW_USER_DATA',
        'AWAITING_UPDATE_INTERVAL', 'AWAITING_LOGGING_LEVEL', 'AWAITING_RESUME_UPLOAD',
        'AWAITING_NEW_ADMIN', 'AWAITING_NEW_ADMIN_CONFIRM', 'AWAITING_RESUMES_LIMIT'
    ]

    has_active_admin_state = any(context.user_data.get(state_key, False) for state_key in admin_states)

    if has_active_admin_state:
        logger.info("Пользователь в административном состоянии - пропускаем обычную обработку")
        return

    try:
        await user_manager.update_last_login_async(user_id)
        logger.info(f"🔄 Обновлено время входа для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления времени входа для {user_id}: {e}")

    if user_message == '⚙️ Панель управления' and user_manager.is_admin(user_id):
        from admin_handlers import admin_panel
        await admin_panel(update, context)
        return

    logger.info(f"🔍 Запуск поиска PDF для пользователя {user_id}: {user_message}")

    can_request, message = await user_manager.can_make_request_async(user_id)
    if not can_request:
        error_message = (
            f"{message}\n\n"
            f"🆔 Ваш ID: `{user_id}`\n\n"
            f"📩 Отправьте ID администратору, чтобы получить доступ:\n"
            f"{admin_contact}"
        )
        await update.message.reply_text(error_message)
        return

    increment_result = await user_manager.increment_request_count_async(user_id)
    if increment_result:
        logger.info(f"📊 Увеличен счетчик запросов для {user_id}")
    else:
        logger.error(f"❌ Ошибка увеличения счетчика запросов для {user_id}")

    await update.message.reply_text(
        f"🔍 Поиск по резюме...\n\n"
    )
    context.user_data['current_search'] = 'PDF поиск'
    await handle_pdf_text_search(update, context)


@require_auth
async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Обработчик ошибок с логированием """
    error_msg = f'Ошибка: {context.error}'
    logger.error(error_msg, exc_info=True)

    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text(
                '❌ Произошла ошибка. Попробуйте позже или обратитесь к администратору.',
                reply_markup=get_main_keyboard(update.effective_user.id)
            )
        except Exception as e:
            logger.error(f'Ошибка при отправке сообщения об ошибке: {e}')


async def safe_send_pdf(update: Update, pdf_path: str, caption: str, filename: str, max_retries: int = 2) -> bool:
    """ Отправка PDF с учетом лимитов """
    user_id = update.effective_user.id

    can_download, message = user_manager.can_download_resume(user_id)
    if not can_download:
        logger.warning(f"🚫 Лимит резюме для пользователя {user_id}: {message}")
        await update.message.reply_text(message)
        return False

    user_before = user_manager.get_user(user_id)
    stats_before = user_manager.get_resume_stats(user_id)
    logger.info(f"📥 Пользователь {user_id} скачивает резюме: {filename}")
    logger.info(f"📊 Статистика до: сегодня={stats_before['resumes_today']}, месяц={stats_before['resumes_this_month']}, всего={stats_before['resumes_total']}")

    for attempt in range(max_retries):
        try:
            if update.callback_query and update.callback_query.message:
                message = update.callback_query.message
            elif update.message:
                message = update.message
            else:
                logger.error("❌ Не удалось определить контекст для отправки сообщения")
                return False

            if not os.path.exists(pdf_path):
                logger.error(f"❌ Файл не найден: {pdf_path}")
                return False

            file_size = os.path.getsize(pdf_path) / (1024 * 1024)
            if file_size > 10:
                await update.message.reply_text(
                    f"⚠️ Файл слишком большой ({file_size:.1f}MB). Оптимизирую отправку..."
                )
            with open(pdf_path, 'rb') as pdf_file:
                await message.reply_document(
                    document=pdf_file,
                    filename=filename,
                    caption=caption,
                    read_timeout=30,
                    write_timeout=60,
                    connect_timeout=30
                )
                success = user_manager.increment_resume_count(user_id)
                user_after = user_manager.get_user(user_id)
                if user_after:
                    logger.info(
                        f"✅ Данные после скачивания: сегодня={user_after['resumes_today']}, месяц={user_after['resumes_this_month']}, всего={user_after['resumes_total']}")

                    if (user_after['resumes_today'] == user_before['resumes_today'] + 1 and
                            user_after['resumes_this_month'] == user_before['resumes_this_month'] + 1 and
                            user_after['resumes_total'] == user_before['resumes_total'] + 1):
                        logger.info(f"✅ Счетчик резюме успешно увеличен для {user_id}")
                        return True
                    else:
                        logger.error(f"❌ Данные не изменились для {user_id}")
                        return False
                else:
                    logger.error(f"❌ Не удалось получить обновленные данные для {user_id}")
                    return False

        except TimedOut:
            logger.warning(f"⚠️ Таймаут при отправке {filename}, попытка {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки PDF {filename}: {e}")
            return False
    return False