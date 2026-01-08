from config import BOT_TOKEN, RESUMES_FOLDER
import os
import logging
from pdf_indexer import pdf_indexer
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler
from telegram.ext import CallbackQueryHandler
from handlers import (start, handle_message, error_handler, handle_pdf_search_decision, get_my_id, quick_get_id, check_index_status)
from admin_handlers import (
    admin_panel, show_users_list, change_requests_limit, change_access_days,
    reset_counters, handle_resumes_limit_input, show_users_panel, show_limits_panel, show_database_panel, show_settings_panel,
    clear_search_cache, show_system_stats, deactivate_user_command, activate_user_command, handle_resume_upload, handle_update_interval_input,
    cancel_upload, handle_logging_level_input, change_resumes_limit, add_user_with_limits, change_admin_panel, handle_new_admin_input,
    handle_limits_input, handle_deactivate_id_input, handle_activate_id_input, handle_admin_change_confirmation, upload_resumes,
    handle_new_user_with_limits, delete_user_command, handle_delete_id_input, cancel_operation, change_update_interval, change_logging,
    AWAITING_LIMITS_INPUT, AWAITING_DEACTIVATE_ID, AWAITING_ACTIVATE_ID, AWAITING_NEW_USER_DATA, AWAITING_DELETE_ID, AWAITING_RESUME_UPLOAD,
    AWAITING_NEW_ADMIN_CONFIRM, AWAITING_UPDATE_INTERVAL, AWAITING_LOGGING_LEVEL, AWAITING_NEW_ADMIN, AWAITING_RESUMES_LIMIT
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """ Основная функция запуска бота """

    application = Application.builder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).build()

    # === ОБРАБОТЧИКИ CALLBACK QUERIES (должны быть первыми) ===

    # Специфичные обработчики callback queries
    callback_patterns = [
        ("show_other_results", handle_pdf_search_decision),
        ("finish_search", handle_pdf_search_decision)
    ]

    for pattern, handler in callback_patterns:
        application.add_handler(CallbackQueryHandler(handler, pattern=f"^{pattern}$"))

    # === БАЗОВЫЕ КОМАНДЫ ===
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_my_id", get_my_id))
    application.add_handler(CommandHandler("id", quick_get_id))
    application.add_handler(CommandHandler("index_status", check_index_status))

    # === CONVERSATION HANDLERS (важен порядок!) ===

    # ConversationHandler для добавления пользователя
    add_user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^➕ Добавить пользователя$'), add_user_with_limits)],
        states={
            AWAITING_NEW_USER_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_user_with_limits)]
        },
        fallbacks=[CommandHandler('cancel', cancel_operation)]
    )
    application.add_handler(add_user_conv)

    # ConversationHandler для удаления пользователя
    delete_user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🗑️ Удалить пользователя$'), delete_user_command)],
        states={
            AWAITING_DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_id_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel_operation)]
    )
    application.add_handler(delete_user_conv)

    change_admin_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^👑 Сменить администратора$'), change_admin_panel)],
        states={
            AWAITING_NEW_ADMIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_admin_input)
            ],
            AWAITING_NEW_ADMIN_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_change_confirmation)
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel_operation),
            MessageHandler(filters.Regex('^⬅️ Назад в админку$'), admin_panel)
        ]
    )
    application.add_handler(change_admin_conv)

    # ConversationHandler для загрузки резюме
    resume_upload_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📤 Загрузка новых резюме$'), upload_resumes)],
        states={
            AWAITING_RESUME_UPLOAD: [MessageHandler(filters.ATTACHMENT | filters.TEXT, handle_resume_upload)]
        },
        fallbacks=[CommandHandler('cancel', cancel_upload)]
    )
    application.add_handler(resume_upload_conv)

    # ConversationHandler для управления лимитами
    limits_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^🔢 Лимит запросов$'), change_requests_limit),
            MessageHandler(filters.Regex('^📅 Лимит дней$'), change_access_days)
        ],
        states={
            AWAITING_LIMITS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limits_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel_operation)]
    )
    application.add_handler(limits_conv_handler)

    resumes_limit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📄 Лимит резюме$'), change_resumes_limit)],
        states={
            AWAITING_RESUMES_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_resumes_limit_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel_operation)]
    )
    application.add_handler(resumes_limit_conv)

    # ConversationHandler для активации/деактивации пользователей
    user_status_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^🔒 Деактивировать пользователя$'), deactivate_user_command),
            MessageHandler(filters.Regex('^🔓 Активировать пользователя$'), activate_user_command)
        ],
        states={
            AWAITING_DEACTIVATE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deactivate_id_input)],
            AWAITING_ACTIVATE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_activate_id_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel_operation)]
    )
    application.add_handler(user_status_conv_handler)


    # ConversationHandler для настроек системы
    settings_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^🕐 Изменить интервал обновления$'), change_update_interval),
            MessageHandler(filters.Regex('^📊 Логирование$'), change_logging),
        ],
        states={
            AWAITING_UPDATE_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_update_interval_input)],
            AWAITING_LOGGING_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_logging_level_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel_operation)]
    )
    application.add_handler(settings_conv_handler)

    # === ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ===
    admin_handlers = [
        ('^⚙️ Панель управления$', admin_panel),
        ('^📊 Пользователи$', show_users_panel),
        ('^📊 Лимиты$', show_limits_panel),
        ('^📈 Статистика$', show_system_stats),
        ('^📁 Управление PDF базой$', show_database_panel),
        ('^⚙️ Настройки системы$', show_settings_panel),
        ('^👑 Сменить администратора$', change_admin_panel)
    ]

    for pattern, handler in admin_handlers:
        application.add_handler(MessageHandler(filters.Regex(pattern), handler))

    # === ОБРАБОТЧИКИ КНОПОК ВНУТРИ ПАНЕЛЕЙ ===
    panel_handlers = [
        # Кнопки панели пользователей
        ('^🔓 Активировать пользователя$', activate_user_command),
        ('^🔒 Деактивировать пользователя$', deactivate_user_command),
        ('^➕ Добавить пользователя$', add_user_with_limits),
        ('^🗑️ Удалить пользователя$', delete_user_command),
        ('^✅ Активные$', show_users_list),
        ('^❌ Деактивированные$', show_users_list),
        ('^⏰ Истек срок$', show_users_list),

        # Кнопки панели лимитов
        ('^🔢 Лимит запросов$', change_requests_limit),
        ('^📅 Лимит дней$', change_access_days),
        ('^📄 Лимит резюме$', change_resumes_limit),
        ('^🔄 Сбросить счетчики$', reset_counters),

        # Кнопки панели PDF базы
        ('^📤 Загрузка новых резюме$', upload_resumes),
        ('^🧹 Очистить кэш поиска$', clear_search_cache),

        # Кнопки панели настроек
        ('^🕐 Изменить интервал обновления$', change_update_interval),
        ('^📊 Логирование$', change_logging),

        # Навигационные кнопки
        ('^⬅️ Назад в админку$', admin_panel),
    ]

    for pattern, handler in panel_handlers:
        application.add_handler(MessageHandler(filters.Regex(pattern), handler))

    # === ОБРАБОТЧИКИ ИНФОРМАЦИИ ПОЛЬЗОВАТЕЛЯ ===
    info_handlers = [
        ('^🔄 Обновить информацию$', get_my_id),
    ]

    for pattern, handler in info_handlers:
        application.add_handler(MessageHandler(filters.Regex(pattern), handler))

    # === НАВИГАЦИОННЫЕ КНОПКИ ===
    navigation_handlers = [
        ('^⬅️ Назад в админку$', admin_panel),
        ('^⬅️ Назад к поиску$', start),
    ]

    for pattern, handler in navigation_handlers:
        application.add_handler(MessageHandler(filters.Regex(pattern), handler))

    # === ОБРАБОТЧИК ОШИБОК ===
    application.add_error_handler(error_handler)

    # === ОБЩИЙ ОБРАБОТЧИК СООБЩЕНИЙ (должен быть последним!) ===
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Общий обработчик callback queries (должен быть последним)
    application.add_handler(CallbackQueryHandler(handle_pdf_search_decision))

    print("🚀 Бот запущен и готов к работе!")
    print("📊 Функциональность:")
    print("   • 🔍 Быстрый поиск по PDF через индекс")
    print("   • 👥 Управление пользователями")
    print("   • ⏰ Ограничения по времени и запросам")
    print("   • 📈 Статистика и мониторинг")

    print("📚 Проверка индексации PDF файлов...")

    try:
        stats = pdf_indexer.get_index_stats()
        print(f"✅ Индекс базы: {stats['total_indexed_files']} файлов")

        pdf_files = [f for f in os.listdir(RESUMES_FOLDER) if f.lower().endswith('.pdf')]
        if len(pdf_files) > stats['total_indexed_files']:
            print("🔄 Обновление индекса...")
            indexed_count = pdf_indexer.index_all_pdfs(max_workers=4, batch_size=200)
            print(f"✅ Проиндексировано {indexed_count} новых PDF файлов")
        else:
            print("✅ Индекс актуален")

    except Exception as e:
        print(f"⚠️ Ошибка при проверке индекса: {e}")
        print("🔄 Запускаем полную индексацию...")
        try:
            indexed_count = pdf_indexer.index_all_pdfs(max_workers=4, batch_size=200)
            print(f"✅ Проиндексировано {indexed_count} PDF файлов")
        except Exception as e2:
            print(f"❌ Критическая ошибка индексации: {e2}")

    try:
        application.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске бота: {e}")
        print(f"❌ Бот остановлен из-за ошибки: {e}")


if __name__ == '__main__':
    main()