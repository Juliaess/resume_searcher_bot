from telegram import ReplyKeyboardMarkup
from auth import user_manager


def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """ Клавиатура """
    if user_manager.is_admin(user_id):
        keyboard = [['⚙️ Панель управления']]
    else:
        keyboard = []
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура администратора """
    return ReplyKeyboardMarkup(
        [
            ['📊 Пользователи', '📊 Лимиты'],
            ['📈 Статистика', '📁 Управление PDF базой'],
            ['⚙️ Настройки системы', '👑 Сменить администратора'],
            ['⬅️ Назад к поиску']
        ],
        resize_keyboard=True
    )


def get_limits_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура управления лимитами """
    return ReplyKeyboardMarkup(
        [
            ['🔢 Лимит запросов', '📅 Лимит дней'],
            ['📄 Лимит резюме', '🔄 Сбросить счетчики'],
            ['⬅️ Назад в админку']
        ],
        resize_keyboard=True
    )


def get_users_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура управления пользователями """
    return ReplyKeyboardMarkup(
        [
            ['🔓 Активировать пользователя', '🔒 Деактивировать пользователя'],
            ['➕ Добавить пользователя', '🗑️ Удалить пользователя'],
            ['✅ Активные', '❌ Деактивированные'],
            ['⏰ Истек срок', '⬅️ Назад в админку']
        ],
        resize_keyboard=True
    )


def get_database_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура управления базой данных """
    return ReplyKeyboardMarkup(
        [['📤 Загрузка новых резюме', '🧹 Очистить кэш поиска', '⬅️ Назад в админку']],
        resize_keyboard=True
    )


def get_settings_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура настроек системы """
    return ReplyKeyboardMarkup(
        [['🕐 Изменить интервал обновления'], ['📊 Логирование', '⬅️ Назад в админку']],
        resize_keyboard=True
    )


def get_confirm_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура подтверждения смены администратора """
    return ReplyKeyboardMarkup(
        [
            ['✅ Подтвердить смену админа', '❌ Отменить'],
            ['⬅️ Назад в админку']
        ],
        resize_keyboard=True
    )


def get_logging_keyboard() -> ReplyKeyboardMarkup:
    """ Клавиатура настройки логирования """
    return ReplyKeyboardMarkup(
        [
            ['🔍 DEBUG', 'ℹ️ INFO'],
            ['⚠️ WARNING', '❌ ERROR'],
            ['⬅️ Назад в админку']
        ],
        resize_keyboard=True
    )