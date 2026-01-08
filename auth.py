import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple, Any
import logging
import threading
from contextlib import contextmanager
import aiosqlite
from contextlib import asynccontextmanager
from admin_config import DEFAULT_ADMIN_ID, ADMIN_CONTACT

logger = logging.getLogger(__name__)


class UserManager:
    def __init__(self, db_path: str = 'data/users.db'):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.init_database()
        self.update_database_schema()
        self.update_admin_contact_in_db()

    async def update_last_login_async(self, telegram_id: int):
        """ Асинхронное обновление времени последнего входа """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()
                await cursor.execute('''
                    UPDATE users SET last_login = CURRENT_TIMESTAMP 
                    WHERE telegram_id = ?
                ''', (telegram_id,))
                await conn.commit()
        except Exception as e:
            logger.error(f"Ошибка обновления времени входа {telegram_id}: {e}")

    @asynccontextmanager
    async def _get_async_connection(self):
        """ Асинхронное подключение к БД """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout = 5000")
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            yield conn

    async def can_make_request_async(self, telegram_id: int) -> Tuple[bool, str]:
        """ Асинхронная проверка доступа """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()

                await cursor.execute('''
                       SELECT is_active, access_expires, daily_requests_limit, 
                              requests_today, last_request_date, admin_contact
                       FROM users WHERE telegram_id = ?
                   ''', (telegram_id,))

                user_data = await cursor.fetchone()

                if not user_data:
                    return False, "❌ Пользователь не найден"

                (is_active, access_expires, daily_requests_limit,
                 requests_today, last_request_date, admin_contact) = user_data

                admin_contact = self.get_admin_contact()

                if not is_active:
                    return False, f"Чтобы активировать бота обратитесь к администратору {admin_contact}\nВаш ID: {telegram_id}"

                if access_expires:
                    try:
                        expires_date = datetime.fromisoformat(access_expires)
                        if datetime.now() > expires_date:
                            await self.deactivate_user_async(telegram_id)
                            return False, f"⏰ Срок доступа истек. Обратитесь к администратору: {admin_contact}"
                    except ValueError as e:
                        logger.error(f"Ошибка парсинга даты для пользователя {telegram_id}: {e}")

                today = datetime.now().date().isoformat()
                if last_request_date and last_request_date != today:
                    await self.reset_daily_requests_async(telegram_id)
                    requests_today = 0

                if daily_requests_limit > 0 and requests_today >= daily_requests_limit:
                    return False, f"📊 Лимит запросов исчерпан ({requests_today}/{daily_requests_limit}). Попробуйте завтра."

                return True, ""

        except Exception as e:
            logger.error(f"Ошибка проверки доступа для {telegram_id}: {e}")
            return False, "❌ Ошибка проверки доступа"

    async def increment_request_count_async(self, telegram_id: int) -> bool:
        """ Асинхронное увеличение счетчика """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()
                today = datetime.now().date().isoformat()

                await cursor.execute('''
                       UPDATE users 
                       SET requests_today = requests_today + 1, last_request_date = ?
                       WHERE telegram_id = ?
                   ''', (today, telegram_id))

                await conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка увеличения счетчика для {telegram_id}: {e}")
            return False

    async def reset_daily_requests_async(self, telegram_id: int) -> bool:
        """ Асинхронный сброс счетчика запросов """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()
                await cursor.execute('UPDATE users SET requests_today = 0 WHERE telegram_id = ?', (telegram_id,))
                await conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка сброса счетчика для {telegram_id}: {e}")
            return False

    async def deactivate_user_async(self, telegram_id: int) -> bool:
        """ Асинхронная деактивация пользователя """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()
                await cursor.execute('UPDATE users SET is_active = 0 WHERE telegram_id = ?', (telegram_id,))
                await conn.commit()
                logger.info(f"Пользователь {telegram_id} деактивирован (async)")
                return True
        except Exception as e:
            logger.error(f"Ошибка деактивации пользователя {telegram_id}: {e}")
            return False

    async def get_user_async(self, telegram_id: int) -> Optional[Dict]:
        """ Асинхронное получение информации о пользователе """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()

                await cursor.execute('''
                       SELECT telegram_id, username, first_name, last_name, role, is_active, 
                              created_at, last_login, access_level, daily_requests_limit,
                              requests_today, last_request_date, access_expires, admin_contact,
                              resumes_limit, resumes_today, resumes_this_month, resumes_total,
                              last_resume_date, monthly_reset_date
                       FROM users WHERE telegram_id = ?
                   ''', (telegram_id,))

                row = await cursor.fetchone()

                if row:
                    return {
                        'telegram_id': row[0],
                        'username': row[1],
                        'first_name': row[2],
                        'last_name': row[3],
                        'role': row[4],
                        'is_active': bool(row[5]),
                        'created_at': row[6],
                        'last_login': row[7],
                        'access_level': row[8],
                        'daily_requests_limit': row[9],
                        'requests_today': row[10],
                        'last_request_date': row[11],
                        'access_expires': row[12],
                        'admin_contact': row[13],
                        'resumes_limit': row[14],
                        'resumes_today': row[15],
                        'resumes_this_month': row[16],
                        'resumes_total': row[17],
                        'last_resume_date': row[18],
                        'monthly_reset_date': row[19]
                    }
                return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя {telegram_id}: {e}")
            return None

    def update_database_schema(self):
        """ Обновление схемы базы данных до актуальной версии """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                new_columns = [
                    ('resumes_limit', 'INTEGER DEFAULT 0'),
                    ('resumes_today', 'INTEGER DEFAULT 0'),
                    ('resumes_this_month', 'INTEGER DEFAULT 0'),
                    ('resumes_total', 'INTEGER DEFAULT 0'),
                    ('last_resume_date', 'DATE'),
                    ('monthly_reset_date', 'TEXT')
                ]

                for column_name, column_type in new_columns:
                    try:
                        cursor.execute(f'SELECT {column_name} FROM users LIMIT 1')
                    except sqlite3.OperationalError:
                        cursor.execute(f'ALTER TABLE users ADD COLUMN {column_name} {column_type}')
                        logger.info(f"Добавлено поле {column_name} в таблицу users")

                conn.commit()
                logger.info("Схема базы данных обновлена")

        except Exception as e:
            logger.error(f"Ошибка при обновлении схемы БД: {e}")

    @contextmanager
    def _get_connection(self):
        """ Контекстный менеджер для безопасного доступа к БД """
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
                yield conn
            finally:
                conn.close()

    def update_user_role(self, telegram_id: int, new_role: str) -> bool:
        """ Обновление роли пользователя """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (telegram_id,))
                current_role = cursor.fetchone()
                current_role = current_role[0] if current_role else 'unknown'

                cursor.execute(
                    'UPDATE users SET role = ? WHERE telegram_id = ?',
                    (new_role, telegram_id)
                )
                conn.commit()

                logger.info(
                    f"Роль пользователя {telegram_id} изменена: "
                    f"{current_role} -> {new_role}"
                )
                return True
        except Exception as e:
            logger.error(f"Ошибка изменения роли пользователя {telegram_id}: {e}")
            return False

    def get_admin_contact(self) -> str:
        """ Получение контакта администратора """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                        SELECT username, first_name, telegram_id, admin_contact
                        FROM users 
                        WHERE role = 'admin'
                        ORDER BY last_login DESC, last_login DESC
                        LIMIT 1
                    ''')

                admin_data = cursor.fetchone()

                if admin_data:
                    username, first_name, telegram_id, admin_contact = admin_data

                    if ADMIN_CONTACT and ADMIN_CONTACT.strip():
                        return ADMIN_CONTACT
                    elif username and username.strip():
                        return f"@{username}"
                    elif first_name and first_name.strip():
                        return f"{first_name} (ID: {telegram_id})"
                    else:
                        return f"Администратор (ID: {telegram_id})"
                else:
                    return ADMIN_CONTACT

        except Exception as e:
            logger.error(f"Ошибка получения контакта администратора: {e}")
        return ADMIN_CONTACT

    def init_database(self):
        """ Инициализация базы данных с расширенными полями """
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                role TEXT DEFAULT 'recruiter',
                is_active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                access_level INTEGER DEFAULT 1,
                daily_requests_limit INTEGER DEFAULT 10,
                requests_today INTEGER DEFAULT 0,
                last_request_date DATE,
                access_expires TIMESTAMP,
                admin_contact TEXT DEFAULT '@elenazenka',
                resumes_limit INTEGER DEFAULT 0,
                resumes_today INTEGER DEFAULT 0,
                resumes_this_month INTEGER DEFAULT 0,
                resumes_total INTEGER DEFAULT 0,
                last_resume_date DATE,
                monthly_reset_date DATE
                
            )
        ''')

        cursor.execute('''
                INSERT OR IGNORE INTO users 
                (telegram_id, username, first_name, role, is_active, access_level, daily_requests_limit) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (DEFAULT_ADMIN_ID, 'admin', 'Administrator', 'admin', 1, 0, 0))

        conn.commit()
        conn.close()
        logger.info("База данных пользователей инициализирована")

    def add_user(self, telegram_id: int, username: str = "", first_name: str = "",
                 last_name: str = "", role: str = "recruiter",
                 daily_requests_limit: int = 10, access_days: int = 30, resumes_limit: int = 0) -> bool:
        """ Добавление нового пользователя с настройками доступа """
        try:
            is_admin = telegram_id == DEFAULT_ADMIN_ID
            existing_user = self.get_user(telegram_id)
            if existing_user and existing_user.get('is_active'):
                is_active = 1
                access_expires = existing_user.get('access_expires')
                final_daily_limit = existing_user.get('daily_requests_limit', daily_requests_limit)
                final_resumes_limit = existing_user.get('resumes_limit', resumes_limit)
            elif is_admin:
                role = 'admin'
                is_active = 1
                final_daily_limit = 0
                final_resumes_limit = 0
                access_expires = None
            else:
                is_active = 0
                final_daily_limit = daily_requests_limit
                final_resumes_limit = resumes_limit
                access_expires = datetime.now() + timedelta(days=access_days) if access_days > 0 else None
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (telegram_id, username, first_name, last_name, role, is_active, 
                 daily_requests_limit, access_expires, resumes_limit, admin_contact) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (telegram_id, username, first_name, last_name, role, is_active,
                  final_daily_limit, access_expires, final_resumes_limit, '@elenazenka'))

            conn.commit()
            conn.close()

            logger.info(f"✅ Добавлен/обновлен пользователь: {telegram_id} | "
                   f"Username: @{username or 'нет'} | "
                   f"Имя: {first_name or 'нет'} | "
                   f"Фамилия: {last_name or 'нет'}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления пользователя: {e}")
            return False

    def add_user_by_admin(self, telegram_id: int, username: str = "", first_name: str = "",
                          last_name: str = "", role: str = "recruiter",
                          daily_requests_limit: int = 10, access_days: int = 30, resumes_limit: int = 0) -> bool:
        """ Добавление нового пользователя АДМИНОМ с автоматической активацией """
        try:
            access_expires = datetime.now() + timedelta(days=access_days) if access_days > 0 else None

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (telegram_id, username, first_name, last_name, role, is_active, 
                 daily_requests_limit, access_expires, resumes_limit, admin_contact) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (telegram_id, username or "", first_name or "", last_name or "", role, 1,
                  daily_requests_limit, access_expires, resumes_limit, '@elenazenka'))

            conn.commit()
            conn.close()

            logger.info(f"✅ Админ добавил и АКТИВИРОВАЛ пользователя: {telegram_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления пользователя админом: {e}")
            return False

    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """ Получение информации о пользователе """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                        SELECT telegram_id, username, first_name, last_name, role, is_active, 
                               created_at, last_login, access_level, daily_requests_limit,
                               requests_today, last_request_date, access_expires, admin_contact,
                               resumes_limit, resumes_today, resumes_this_month, resumes_total,
                               last_resume_date, monthly_reset_date
                        FROM users WHERE telegram_id = ?
                    ''', (telegram_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                username = row[1] or ""
                first_name = row[2] if row[2] and row[2].strip() and row[2] != "Без имени" else ""
                last_name = row[3] if row[3] and row[3].strip() else ""

                if first_name and last_name:
                    display_name = f"{first_name} {last_name}"
                elif first_name:
                    display_name = first_name
                elif last_name:
                    display_name = last_name
                elif username:
                    display_name = f"@{username}"
                else:
                    display_name = f"Пользователь {telegram_id}"

                return {
                    'telegram_id': row[0],
                    'username': username,
                    'first_name': first_name,
                    'last_name': last_name,
                    'display_name': display_name,
                    'role': row[4],
                    'is_active': bool(row[5]),
                    'created_at': row[6],
                    'last_login': row[7],
                    'access_level': row[8],
                    'daily_requests_limit': row[9],
                    'requests_today': row[10],
                    'last_request_date': row[11],
                    'access_expires': row[12],
                    'admin_contact': row[13],
                    'resumes_limit': row[14],
                    'resumes_today': row[15],
                    'resumes_this_month': row[16],
                    'resumes_total': row[17],
                    'last_resume_date': row[18],
                    'monthly_reset_date': row[19]
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя: {e}")
            return None

    def update_last_login(self, telegram_id: int):
        """ Обновление времени последнего входа """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE users SET last_login = CURRENT_TIMESTAMP 
                WHERE telegram_id = ?
            ''', (telegram_id,))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка обновления времени входа: {e}")

    def can_make_request(self, telegram_id: int) -> Tuple[bool, str]:
        """ Проверка возможности выполнения запроса """
        user = self.get_user(telegram_id)
        admin_contact = self.get_admin_contact()
        if not user or not user['is_active']:
            return False, f"🔐 Аккаунт деактивирован. Для доступа к боту обратитесь к администратору {admin_contact}"

        if user['access_expires']:
            try:
                expires_date = datetime.fromisoformat(user['access_expires'])
                if datetime.now() > expires_date:
                    self.deactivate_user(telegram_id)
                    return False, f"⏰ Срок доступа истек. Обратитесь к администратору: {admin_contact}"
            except ValueError as e:
                logger.error(f"Ошибка парсинга даты для пользователя {telegram_id}: {e}")

        today = datetime.now().date()
        last_request_date = user['last_request_date']

        if last_request_date:
            try:
                last_date = datetime.fromisoformat(last_request_date).date()
                if last_date != today:
                    self.reset_daily_requests(telegram_id)
                    user['requests_today'] = 0
            except ValueError as e:
                logger.error(f"Ошибка парсинга даты запроса для пользователя {telegram_id}: {e}")
                self.reset_daily_requests(telegram_id)

        if user['daily_requests_limit'] > 0 and user['requests_today'] >= user['daily_requests_limit']:
            return False, f"📊 Лимит запросов исчерпан ({user['requests_today']}/{user['daily_requests_limit']}). Попробуйте завтра."

        return True, ""

    def increment_request_count(self, telegram_id: int) -> bool:
        """ Увеличение счетчика запросов """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            today = datetime.now().date().isoformat()

            cursor.execute('''
                    UPDATE users 
                    SET requests_today = requests_today + 1, last_request_date = ?
                    WHERE telegram_id = ?
                ''', (today, telegram_id))

            conn.commit()
            return True

    def reset_daily_requests(self, telegram_id: int) -> bool:
        """ Сброс дневного счетчика запросов """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE users SET requests_today = 0 
                WHERE telegram_id = ?
            ''', (telegram_id,))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Ошибка сброса счетчика запросов: {e}")
            return False

    def update_user_limits(self, telegram_id: int, daily_requests_limit: int = None,
                           access_days: int = None) -> bool:
        """ Обновление лимитов пользователя """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            updates = []
            params = []

            if daily_requests_limit is not None:
                updates.append("daily_requests_limit = ?")
                params.append(daily_requests_limit)

            if access_days is not None:
                access_expires = datetime.now() + timedelta(days=access_days) if access_days > 0 else None
                updates.append("access_expires = ?")
                params.append(access_expires)

            if updates:
                params.append(telegram_id)
                query = f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ?"
                cursor.execute(query, params)

            conn.commit()
            conn.close()
            logger.info(f"Обновлены лимиты пользователя {telegram_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления лимитов пользователя: {e}")
            return False

    def deactivate_user(self, telegram_id: int) -> bool:
        """ Деактивация пользователя """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE users SET is_active = 0 WHERE telegram_id = ?
            ''', (telegram_id,))

            conn.commit()
            conn.close()
            logger.info(f"Пользователь {telegram_id} деактивирован")
            return True
        except Exception as e:
            logger.error(f"Ошибка деактивации пользователя: {e}")
            return False

    def activate_user(self, telegram_id: int, access_days: int = 30) -> bool:
        """ Активация пользователя с установкой срока доступа """
        try:
            access_expires = datetime.now() + timedelta(days=access_days) if access_days > 0 else None

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE users SET is_active = 1, access_expires = ? 
                WHERE telegram_id = ?
            ''', (access_expires, telegram_id))

            conn.commit()
            conn.close()
            logger.info(f"Пользователь {telegram_id} активирован на {access_days} дней")
            return True
        except Exception as e:
            logger.error(f"Ошибка активации пользователя: {e}")
            return False

    def get_all_users(self) -> List[Dict]:
        """ Получение списка всех пользователей """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT telegram_id, username, first_name, last_name, role, is_active, 
                           created_at, last_login, daily_requests_limit, requests_today,
                           access_expires, resumes_limit, resumes_today, resumes_this_month, resumes_total
                    FROM users ORDER BY created_at DESC
                ''')

                users = []
                for row in cursor.fetchall():
                    username = row[1] or ""
                    first_name = row[2] if row[2] and row[2].strip() and row[2] != "Без имени" else ""
                    last_name = row[3] if row[3] and row[3].strip() else ""

                    if first_name and last_name:
                        display_name = f"{first_name} {last_name}"
                    elif first_name:
                        display_name = first_name
                    elif last_name:
                        display_name = last_name
                    elif username:
                        display_name = f"@{username}"
                    else:
                        display_name = f"Пользователь {row[0]}"

                    user_data = {
                        'telegram_id': row[0],
                        'username': username,
                        'first_name': first_name,
                        'last_name': last_name,
                        'display_name': display_name,
                        'role': row[4],
                        'is_active': bool(row[5]),
                        'created_at': row[6],
                        'last_login': row[7],
                        'daily_requests_limit': row[8],
                        'requests_today': row[9],
                        'access_expires': row[10],
                        'resumes_limit': row[11],
                        'resumes_today': row[12],
                        'resumes_this_month': row[13],
                        'resumes_total': row[14],
                        'days_remaining': self._calculate_days_remaining(row[10]) if row[10] else None,
                        'status': self._determine_user_status(bool(row[5]), row[10])
                    }
                    users.append(user_data)

                return users
        except Exception as e:
            logger.error(f"Ошибка получения списка пользователей: {e}")
            return []

    def _determine_user_status(self, is_active: bool, access_expires: str) -> str:
        """ Определение статуса пользователя """
        if not is_active:
            return "deactivated"

        if access_expires:
            try:
                expires_date = datetime.fromisoformat(access_expires)
                if datetime.now() > expires_date:
                    return "expired"
            except ValueError:
                pass

        return "active"

    def _calculate_days_remaining(self, access_expires) -> int | None:
        """ Расчет оставшихся дней доступа """
        if not access_expires:
            return None
        expires_date = datetime.fromisoformat(access_expires)
        return max(0, (expires_date - datetime.now()).days)

    def is_user_active(self, telegram_id: int) -> bool:
        """ Проверка активности пользователя """
        user = self.get_user(telegram_id)
        return user and user['is_active'] and (
                not user['access_expires'] or datetime.now() <= datetime.fromisoformat(user['access_expires'])
        )

    def is_admin(self, telegram_id: int) -> bool:
        """ Проверка прав администратора """
        user = self.get_user(telegram_id)
        return user and user['is_active'] and user['role'] == 'admin'

    def set_admin_contact(self, contact_info: str) -> bool:
        """ Установка контакта администратора для всех пользователей """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE users SET admin_contact = ? WHERE role = 'recruiter'
            ''', (contact_info,))

            conn.commit()
            conn.close()
            logger.info(f"Установлен контакт администратора: {contact_info}")
            return True
        except Exception as e:
            logger.error(f"Ошибка установки контакта администратора: {e}")
            return False

    def delete_user(self, telegram_id: int) -> bool:
        """ Удаление пользователя из базы данных """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM users WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
            conn.close()

            logger.info(f"Пользователь {telegram_id} удален из базы данных")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления пользователя {telegram_id}: {e}")
            return False

    def save_system_setting(self, key: str, value: str) -> bool:
        """ Сохранение системных настроек """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                INSERT OR REPLACE INTO system_settings (key, value) 
                VALUES (?, ?)
            ''', (key, value))

            conn.commit()
            conn.close()
            logger.info(f"Сохранена системная настройка: {key} = {value}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения системной настройки: {e}")
            return False

    def get_system_setting(self, key: str, default: str = None) -> str:
        """ Получение системных настроек """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('SELECT value FROM system_settings WHERE key = ?', (key,))
            result = cursor.fetchone()
            conn.close()

            return result[0] if result else default
        except Exception as e:
            logger.error(f"Ошибка получения системной настройки: {e}")
            return default

    def can_download_resume(self, telegram_id: int) -> Tuple[bool, str]:
        """ Проверка возможности скачивания резюме """
        user = self.get_user(telegram_id)
        if not user:
            return False, "Пользователь не найден"

        self._check_monthly_reset(telegram_id)

        user = self.get_user(telegram_id)
        admin_contact = self.get_admin_contact()

        today = datetime.now().date().isoformat()
        if user['last_resume_date'] != today:
            self.reset_daily_resumes(telegram_id)
            user = self.get_user(telegram_id)

        if user['resumes_limit'] > 0:
            if user['resumes_today'] >= user['resumes_limit']:
                return False, f"📊 Дневной лимит резюме исчерпан ({user['resumes_today']}/{user['resumes_limit']})\n\nДля увеличения лимита обратитесь к админу {admin_contact}"

            if user['resumes_this_month'] >= user['resumes_limit']:
                return False, f"📅 Месячный лимит резюме исчерпан ({user['resumes_this_month']}/{user['resumes_limit']})\n\nДля увеличения лимита обратитесь к админу {admin_contact}"

        return True, ""

    def increment_resume_count(self, telegram_id: int) -> bool:
        """ Увеличение счетчика скачанных резюме """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().date().isoformat()

                cursor.execute(
                    'SELECT resumes_today, resumes_this_month, resumes_total FROM users WHERE telegram_id = ?',
                    (telegram_id,))
                current = cursor.fetchone()
                if current:
                    logger.info(f"📊 ДО увеличения для {telegram_id}: today={current[0]}, month={current[1]}, total={current[2]}")

                cursor.execute('''
                    UPDATE users 
                    SET resumes_today = resumes_today + 1,
                        resumes_this_month = resumes_this_month + 1,
                        resumes_total = resumes_total + 1,
                        last_resume_date = ?
                    WHERE telegram_id = ?
                ''', (today, telegram_id))

                conn.commit()

                cursor.execute(
                    'SELECT resumes_today, resumes_this_month, resumes_total FROM users WHERE telegram_id = ?',
                    (telegram_id,))
                updated = cursor.fetchone()
                if updated:
                    logger.info(f"📊 ПОСЛЕ увеличения для {telegram_id}: today={updated[0]}, month={updated[1]}, total={updated[2]}")

                if current and updated:
                    if (updated[0] == current[0] + 1 and
                            updated[1] == current[1] + 1 and
                            updated[2] == current[2] + 1):
                        logger.info(f"✅ Увеличен счетчик резюме для {telegram_id}")
                        return True
                    else:
                        logger.warning(f"⚠️ Данные не изменились для {telegram_id}")
                        return False
                else:
                    logger.warning(f"⚠️ Не удалось проверить обновление для {telegram_id}")
                    return False

        except Exception as e:
            logger.error(f"❌ Ошибка увеличения счетчика резюме: {e}")
            return False

    def reset_daily_resumes(self, telegram_id: int) -> bool:
        """ Сброс дневного счетчика резюме """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users SET resumes_today = 0 
                    WHERE telegram_id = ?
                ''', (telegram_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка сброса дневных резюме: {e}")
            return False

    def _check_monthly_reset(self, telegram_id: int):
        """ Проверка и сброс месячного счетчика """
        user = self.get_user(telegram_id)
        if not user:
            return

        current_month = datetime.now().strftime('%Y-%m')
        last_reset_month = user['monthly_reset_date']

        if last_reset_month != current_month:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE users 
                        SET resumes_this_month = 0,
                            monthly_reset_date = ?
                        WHERE telegram_id = ?
                    ''', (current_month, telegram_id))
                    conn.commit()
            except Exception as e:
                logger.error(f"Ошибка месячного сброса резюме: {e}")

    def force_monthly_reset_check(self, telegram_id: int):
        """ Принудительная проверка и сброс месячного счетчика """
        self._check_monthly_reset(telegram_id)

    async def force_monthly_reset_check_async(self, telegram_id: int):
        """ Асинхронная принудительная проверка и сброс месячного счетчика """
        await self._check_monthly_reset_async(telegram_id)

    def update_resumes_limit(self, telegram_id: int, resumes_limit: int) -> bool:
        """ Обновление лимита резюме """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users SET resumes_limit = ? 
                    WHERE telegram_id = ?
                ''', (resumes_limit, telegram_id))
                conn.commit()
                logger.info(f"Обновлен лимит резюме пользователя {telegram_id}: {resumes_limit}")
                return True
        except Exception as e:
            logger.error(f"Ошибка обновления лимита резюме: {e}")
            return False

    def get_resume_stats(self, telegram_id: int) -> Dict[str, Any]:
        """ Получение статистики по резюме """
        user = self.get_user(telegram_id)
        if not user:
            return {}

        self.force_daily_reset_check(telegram_id)
        self._check_monthly_reset(telegram_id)
        user = self.get_user(telegram_id)

        return {
            'resumes_today': user['resumes_today'],
            'resumes_this_month': user['resumes_this_month'],
            'resumes_total': user['resumes_total'],
            'resumes_limit': user['resumes_limit'],
            'monthly_reset_date': user['monthly_reset_date']
        }

    async def can_download_resume_async(self, telegram_id: int) -> Tuple[bool, str]:
        """ Асинхронная проверка возможности скачивания резюме """
        try:
            user = await self.get_user_async(telegram_id)
            if not user:
                return False, "❌ Пользователь не найден"

            await self._check_monthly_reset_async(telegram_id)

            today = datetime.now().date().isoformat()
            if user['last_resume_date'] != today:
                await self.reset_daily_resumes_async(telegram_id)

            if user['resumes_limit'] > 0:
                if user['resumes_today'] >= user['resumes_limit']:
                    return False, f"📊 Дневной лимит резюме исчерпан ({user['resumes_today']}/{user['resumes_limit']})"

                if user['resumes_this_month'] >= user['resumes_limit']:
                    return False, f"📅 Месячный лимит резюме исчерпан ({user['resumes_this_month']}/{user['resumes_limit']})"

            return True, ""

        except Exception as e:
            logger.error(f"❌ Ошибка проверки лимита резюме для {telegram_id}: {e}")
            return False, "❌ Ошибка проверки лимита"

    async def is_admin_async(self, telegram_id: int) -> bool:
        """ Асинхронная проверка прав администратора """
        user = await self.get_user_async(telegram_id)
        return user and user['is_active'] and user['role'] == 'admin'

    async def _check_monthly_reset_async(self, telegram_id: int):
        """ Асинхронная проверка и сброс месячного счетчика """
        user = await self.get_user_async(telegram_id)
        if not user:
            return

        current_month = datetime.now().strftime('%Y-%m')
        last_reset_month = user['monthly_reset_date']

        if last_reset_month != current_month:
            try:
                async with self._get_async_connection() as conn:
                    cursor = await conn.cursor()
                    await cursor.execute('''
                           UPDATE users 
                           SET resumes_this_month = 0,
                               monthly_reset_date = ?
                           WHERE telegram_id = ?
                       ''', (current_month, telegram_id))
                    await conn.commit()
            except Exception as e:
                logger.error(f"❌ Ошибка месячного сброса резюме: {e}")

    async def reset_daily_resumes_async(self, telegram_id: int) -> bool:
        """ Асинхронный сброс дневного счетчика резюме """
        try:
            async with self._get_async_connection() as conn:
                cursor = await conn.cursor()
                await cursor.execute('''
                       UPDATE users SET resumes_today = 0 
                       WHERE telegram_id = ?
                   ''', (telegram_id,))
                await conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка сброса дневных резюме: {e}")
            return False

    def force_daily_reset_check(self, telegram_id: int):
        """Принудительная проверка и сброс дневного счетчика"""
        try:
            user = self.get_user(telegram_id)
            if not user:
                return

            today = datetime.now().date().isoformat()
            last_resume_date = user['last_resume_date']

            if last_resume_date != today:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE users 
                        SET resumes_today = 0,
                            last_resume_date = ?
                        WHERE telegram_id = ?
                    ''', (today, telegram_id))
                    conn.commit()
                    logger.info(f"✅ Дневной сброс резюме для пользователя {telegram_id}")

        except Exception as e:
            logger.error(f"❌ Ошибка дневного сброса резюме: {e}")

    def update_user_info(self, telegram_id: int, username: str = None, first_name: str = None,
                         last_name: str = None) -> bool:
        """ Обновление информации о пользователе """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    'SELECT username, first_name, last_name FROM users WHERE telegram_id = ?',
                    (telegram_id,)
                )
                current_data = cursor.fetchone()

                if current_data:
                    current_username, current_first_name, current_last_name = current_data

                    new_username = username if username is not None and username.strip() != "" else current_username
                    new_first_name = first_name if first_name is not None and first_name.strip() != "" else current_first_name
                    new_last_name = last_name if last_name is not None and last_name.strip() != "" else current_last_name

                    cursor.execute('''
                                   UPDATE users 
                                   SET username = ?, first_name = ?, last_name = ?
                                   WHERE telegram_id = ?
                               ''', (new_username, new_first_name, new_last_name, telegram_id))

                    conn.commit()
                    logger.info(f"✅ Обновлена информация пользователя {telegram_id}: username='{new_username}'")
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка обновления информации пользователя {telegram_id}: {e}")
            return False

    def update_admin_contact_in_db(self):
        """ Обновляет контакт администратора в существующих записях """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE users
                    SET admin_contact = ?
                    WHERE admin_contact IS NULL
                      OR admin_contact = ''
                      OR admin_contact = 'https://t.me/your_admin'
                      OR admin_contact != ?
                ''', (ADMIN_CONTACT, ADMIN_CONTACT))

                updated_count = cursor.rowcount
                conn.commit()
                logger.info(f"Обновлено контактов администраторов: {updated_count}")

        except Exception as e:
            logger.error(f"Ошибка обновления контактов администраторов: {e}")


user_manager = UserManager()