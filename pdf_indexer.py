import re
import os
import time
import sqlite3
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
import pdfplumber
import PyPDF2
from config import RESUMES_FOLDER
from utils import extract_name_from_filename
import aiosqlite
from cache_manager import cache_manager
from cachetools import LRUCache
import asyncio

logger = logging.getLogger(__name__)


class OptimizedPDFIndexer:
    def __init__(self, db_path: str = 'data/pdf_index.db', max_cache_size: int = 500):
        self.db_path = db_path
        self.search_semaphore = asyncio.Semaphore(5)
        self._pdf_texts_cache = LRUCache(maxsize=500)
        self.max_cache_size = max_cache_size
        self._lock = threading.Lock()
        self.init_index_database()
        self._setup_database_optimizations()

    async def optimize_database_indexes(self):
        """Создание оптимизированных индексов"""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()

            await cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_fts_optimized 
                ON pdf_index_fts(content, candidate_name, filename)
            ''')

            await cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_access_stats 
                ON pdf_index(last_accessed, indexed_at)
            ''')

            await conn.commit()

    async def search_indexed_pdf_async(self, search_text: str, limit: int = 20):
        """ Асинхронный поиск с кэшированием """
        cache_key = cache_manager.generate_key("pdf_search", search_text, limit)
        cached_results = await cache_manager.get(cache_key)
        if cached_results:
            logger.info(f"📦 Результаты из кэша для: {search_text[:50]}...")
            return cached_results

        async with self.search_semaphore:
            results = await self._perform_async_search(search_text, limit)
            await cache_manager.set(cache_key, results, ttl=3600)
            return results

    async def _perform_async_search(self, search_text: str, limit: int):
        """ Полнофункциональный асинхронный поиск """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.cursor()

                logger.info(f"🔍 Асинхронный поиск: '{search_text[:80]}...'")

                search_normalized = self._normalize_search_text(search_text)
                key_phrases = self._extract_search_phrases(search_normalized)

                if not key_phrases:
                    logger.warning("❌ Не удалось извлечь фразы, используем fallback")
                    return await self._fallback_search_async(search_text, limit)

                results = []
                seen_filenames = set()

                for phrase in key_phrases[:10]:
                    phrase_results = await self._search_single_phrase_async(cursor, phrase, limit * 2)
                    for result in phrase_results:
                        if result['filename'] not in seen_filenames:
                            result['search_level'] = 'exact_phrase'
                            result['matched_phrase'] = phrase
                            results.append(result)
                            seen_filenames.add(result['filename'])

                if len(results) < 3:
                    combo_results = await self._search_by_word_combinations_async(cursor, key_phrases, limit)
                    for result in combo_results:
                        if result['filename'] not in seen_filenames:
                            result['search_level'] = 'word_combo'
                            results.append(result)
                            seen_filenames.add(result['filename'])

                final_results = []
                for result in results:
                    final_score = self._calculate_relevance(result, search_normalized, key_phrases)
                    result['relevance_score'] = final_score

                    if final_score >= 0.1:
                        final_results.append(result)

                final_results.sort(key=lambda x: x['relevance_score'], reverse=True)
                final_results = final_results[:limit]

                logger.info(f"✅ Асинхронный поиск: найдено {len(final_results)} результатов")
                return final_results

        except Exception as e:
            logger.error(f"❌ Ошибка асинхронного поиска: {e}")
            return await self._fallback_search_async(search_text, limit)

    async def _search_single_phrase_async(self, cursor, phrase: str, limit: int) -> List[dict]:
        """ Асинхронный поиск по одной фразе """
        try:
            await cursor.execute('''
                   SELECT filename, candidate_name, content, 
                          snippet(pdf_index_fts, 2, '<b>', '</b>', '...', 64) as snippet
                   FROM pdf_index_fts 
                   WHERE pdf_index_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?
               ''', (f'"{phrase}"', limit))

            rows = await cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    'filename': row['filename'],
                    'candidate_name': row['candidate_name'],
                    'file_path': os.path.join(RESUMES_FOLDER, row['filename']),
                    'relevance_score': 0.8,
                    'has_exact_match': True,
                    'content': row['content'],
                    'matched_phrase': phrase,
                    'snippet': row['snippet']
                })

            return results
        except Exception as e:
            logger.warning(f"⚠️ Ошибка FTS поиска фразы '{phrase}': {e}")
            return []

    async def _search_by_word_combinations_async(self, cursor, phrases: List[str], limit: int) -> List[dict]:
        """ Асинхронный поиск по комбинациям слов """
        all_words = []
        for phrase in phrases:
            words = re.findall(r'\w{4,}', phrase.lower())
            all_words.extend(words)

        stop_words = {
            'менеджер', 'продажам', 'работы', 'клиентами', 'проект', 'компании',
            'организация', 'управление', 'контроль', 'разработка', 'сопровождение'
        }
        unique_words = [word for word in set(all_words) if word not in stop_words]

        if len(unique_words) < 2:
            return []

        logger.info(f"🔍 Асинхронный поиск по комбинациям слов: {unique_words[:5]}")

        try:
            search_query = ' OR '.join(unique_words[:3])
            await cursor.execute('''
                   SELECT filename, candidate_name, content
                   FROM pdf_index_fts 
                   WHERE pdf_index_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?
               ''', (search_query, limit * 2))

            rows = await cursor.fetchall()
            results = []
            for row in rows:
                content_lower = row['content'].lower()
                matched_count = sum(1 for word in unique_words[:3] if word in content_lower)

                if matched_count >= 2:
                    relevance = min(matched_count / len(unique_words[:3]), 0.6)
                    results.append({
                        'filename': row['filename'],
                        'candidate_name': row['candidate_name'],
                        'file_path': os.path.join(RESUMES_FOLDER, row['filename']),
                        'relevance_score': relevance,
                        'has_exact_match': False,
                        'matched_words': matched_count
                    })

            return results

        except Exception as e:
            logger.error(f"❌ Ошибка асинхронного поиска по комбинациям слов: {e}")
            return []

    async def _fallback_search_async(self, search_text: str, limit: int = 20):
        """ Асинхронный резервный поиск """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.cursor()

                words = re.findall(r'\b\w{4,}\b', search_text.lower())
                stop_words = {'опыт', 'работы', 'работа', 'компания', 'проект'}
                unique_words = [word for word in set(words) if word not in stop_words]

                if not unique_words:
                    unique_words = words[:3]

                logger.info(f"🔄 Асинхронный fallback поиск по словам: {unique_words}")

                all_results = []
                for word in unique_words[:3]:
                    await cursor.execute('''
                           SELECT filename, candidate_name, content
                           FROM pdf_index 
                           WHERE content LIKE ? 
                           LIMIT ?
                       ''', (f'%{word}%', limit))

                    rows = await cursor.fetchall()
                    for row in rows:
                        all_results.append({
                            'filename': row['filename'],
                            'candidate_name': row['candidate_name'],
                            'file_path': os.path.join(RESUMES_FOLDER, row['filename']),
                            'relevance_score': 0.3,
                            'has_exact_match': False,
                            'matched_word': word
                        })

                seen_files = set()
                final_results = []
                for result in all_results:
                    if result['filename'] not in seen_files:
                        seen_files.add(result['filename'])
                        final_results.append(result)

                final_results = final_results[:limit]
                logger.info(f"🔄 Асинхронный fallback поиск: найдено {len(final_results)} результатов")
                return final_results

        except Exception as e:
            logger.error(f"❌ Ошибка асинхронного fallback поиска: {e}")
            return []

    def _setup_database_optimizations(self):
        """ Оптимизация SQLite для больших объемов данных """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA cache_size = -100000")
            cursor.execute("PRAGMA page_size = 4096")
            cursor.execute("PRAGMA mmap_size = 268435456")
            cursor.execute("PRAGMA temp_store = memory")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            conn.commit()

    def init_index_database(self):
        """ Инициализация БД """
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-10000")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pdf_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT UNIQUE NOT NULL,
                    content TEXT,
                    candidate_name TEXT,
                    file_size INTEGER,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                        CREATE VIRTUAL TABLE IF NOT EXISTS pdf_index_fts 
                        USING fts5(
                            filename, 
                            content, 
                            candidate_name,
                            tokenize="porter unicode61"
                        )
                    ''')

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON pdf_index(filename)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_candidate_name ON pdf_index(candidate_name)')

            conn.commit()

        logger.info("✅ База индексации инициализирована")

    def index_all_pdfs(self, max_workers: int = 2, batch_size: int = 100):
        """ Параллельная индексация """
        pdf_files = [f for f in os.listdir(RESUMES_FOLDER) if f.lower().endswith('.pdf')]

        logger.info(f"📚 Начало индексации {len(pdf_files)} PDF файлов...")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename FROM pdf_index")
            existing_files = {row[0] for row in cursor.fetchall()}

        files_to_index = [f for f in pdf_files if f not in existing_files]

        if not files_to_index:
            logger.info("✅ Все файлы уже проиндексированы")
            return len(pdf_files)

        logger.info(f"📝 Файлов для индексации: {len(files_to_index)}")

        indexed_count = 0
        total_files = len(files_to_index)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            batches = [files_to_index[i:i + batch_size]
                       for i in range(0, len(files_to_index), batch_size)]

            for batch_num, batch in enumerate(batches, 1):
                logger.info(f"📦 Обработка батча {batch_num}/{len(batches)} ({len(batch)} файлов)")

                if batch_num > 1:
                    time.sleep(0.5)

                future_to_file = {
                    executor.submit(self._index_single_pdf, filename): filename
                    for filename in batch
                }

                batch_indexed = 0
                for future in as_completed(future_to_file):
                    filename = future_to_file[future]
                    try:
                        if future.result():
                            batch_indexed += 1
                            indexed_count += 1

                        if indexed_count % 50 == 0:
                            progress = (indexed_count / total_files) * 100
                            logger.info(f"📊 Прогресс: {indexed_count}/{total_files} ({progress:.1f}%)")

                    except Exception as e:
                        logger.error(f"❌ Ошибка индексации {filename}: {e}")

                logger.info(f"✅ Батч {batch_num}: индексировано {batch_indexed}/{len(batch)} файлов")

        logger.info(f"🎉 Итог: индексировано {indexed_count} файлов")
        return indexed_count

    def _index_single_pdf(self, filename: str) -> bool:
        """ Индексация одного PDF """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                filepath = os.path.join(RESUMES_FOLDER, filename)
                if not os.path.exists(filepath):
                    return False

                text = self.extract_text_from_pdf(filepath, use_cache=False)
                if not text:
                    return False

                text_clean = self._clean_text(text[:20000])
                candidate_name = extract_name_from_filename(filename)
                file_size = os.path.getsize(filepath)

                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO pdf_index 
                        (filename, content, candidate_name, file_size) 
                        VALUES (?, ?, ?, ?)
                    ''', (filename, text_clean, candidate_name, file_size))

                    cursor.execute('''
                                INSERT OR REPLACE INTO pdf_index_fts 
                                (filename, content, candidate_name) 
                                VALUES (?, ?, ?)
                            ''', (filename, text_clean, candidate_name))

                    conn.commit()
                    return True

            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"⚠️ База заблокирована, повтор {attempt + 1}/{max_retries} для {filename}")
                    time.sleep(0.2 * (attempt + 1))
                    continue
                else:
                    logger.error(f"❌ SQL ошибка для {filename}: {e}")
                    return False
            except Exception as e:
                logger.error(f"❌ Ошибка индексации {filename}: {e}")
                return False

        return False

    def search_indexed_pdf(self, search_text: str, limit: int = 20):
        """ Основной поиск по индексу """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                logger.info(f"🔍 Поиск: '{search_text[:80]}...'")

                search_normalized = self._normalize_search_text(search_text)
                key_phrases = self._extract_search_phrases(search_normalized)

                if not key_phrases:
                    logger.warning("❌ Не удалось извлечь фразы, используем fallback")
                    return self._fallback_search(search_text, limit)

                results = []
                seen_filenames = set()

                for phrase in key_phrases[:10]:
                    phrase_results = self._search_single_phrase(cursor, phrase, limit * 2)
                    for result in phrase_results:
                        if result['filename'] not in seen_filenames:
                            result['search_level'] = 'exact_phrase'
                            result['matched_phrase'] = phrase
                            results.append(result)
                            seen_filenames.add(result['filename'])

                if len(results) < 3:
                    combo_results = self._search_by_word_combinations(cursor, key_phrases, limit)
                    for result in combo_results:
                        if result['filename'] not in seen_filenames:
                            result['search_level'] = 'word_combo'
                            results.append(result)
                            seen_filenames.add(result['filename'])

                final_results = []
                for result in results:
                    final_score = self._calculate_relevance(result, search_normalized, key_phrases)
                    result['relevance_score'] = final_score

                    if final_score >= 0.1:
                        final_results.append(result)

                final_results.sort(key=lambda x: x['relevance_score'], reverse=True)
                final_results = final_results[:limit]

                logger.info(f"✅ Найдено: {len(final_results)} результатов")
                return final_results

        except Exception as e:
            logger.error(f"❌ Ошибка поиска: {e}")
            return self._fallback_search(search_text, limit)

    def _search_single_phrase(self, cursor, phrase: str, limit: int) -> List[dict]:
        """ Поиск по одной фразе """
        try:
            cursor.execute('''
                SELECT filename, candidate_name, content, snippet(pdf_index_fts, 2, '<b>', '</b>', '...', 64) as snippet
                FROM pdf_index_fts 
                WHERE pdf_index_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            ''', (f'"{phrase}"', limit))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'filename': row['filename'],
                    'candidate_name': row['candidate_name'],
                    'file_path': os.path.join(RESUMES_FOLDER, row['filename']),
                    'relevance_score': 0.8,
                    'has_exact_match': True,
                    'content': row['content'],
                    'matched_phrase': phrase,
                    'snippet': row['snippet']
                })

            return results
        except Exception as e:
            logger.warning(f"⚠️ Ошибка FTS поиска фразы '{phrase}': {e}")
            return []

    def _calculate_relevance(self, result: dict, search_text: str, key_phrases: List[str]) -> float:
        """ Расчет релевантности """
        try:
            content = result.get('content', '').lower()
            if not content:
                return result['relevance_score']

            total_score = 0.0

            matched_phrases = [phrase for phrase in key_phrases if phrase.lower() in content]
            for phrase in matched_phrases[:3]:
                phrase_score = min(len(phrase) / 100, 0.5)
                total_score += phrase_score

            if len(matched_phrases) >= 2:
                total_score += 0.2
            elif len(matched_phrases) >= 1:
                total_score += 0.1

            return min(total_score, 1.0)

        except Exception as e:
            logger.error(f"❌ Ошибка расчета релевантности: {e}")
            return result['relevance_score']

    def _extract_search_phrases(self, text: str) -> List[str]:
        """ Извлечение ключевых фраз для поиска """
        phrases = []

        list_patterns = [
            r'(?:\d+[\.\)]|\-|\*|\•|\—)\s*([^\n]{20,200})',
            r'\n\s*([^\n]{20,200})',  # строки с отступом
        ]

        for pattern in list_patterns:
            list_items = re.findall(pattern, text)
            phrases.extend([item.strip() for item in list_items if 20 <= len(item.strip()) <= 200])

        sentences = re.split(r'[.!?\n]', text)
        phrases.extend([s.strip() for s in sentences if 30 <= len(s.strip()) <= 250])

        companies = re.findall(r'(?:компани[яию]|организаци[яию])\s+["«]?([^»"\n]{10,100})', text, re.IGNORECASE)
        phrases.extend(companies)

        positions = re.findall(r'(?:разработка|внедрение|сопровождение)\s+([^\n.,!?]{15,150})', text, re.IGNORECASE)
        phrases.extend(positions)

        filtered_phrases = []
        seen_phrases = set()

        for phrase in phrases:
            if (phrase and phrase not in seen_phrases and 15 <= len(phrase) <= 250 and not self._is_too_general(phrase)):
                seen_phrases.add(phrase)
                filtered_phrases.append(phrase)

        filtered_phrases.sort(key=len, reverse=True)

        logger.info(f"🎯 Извлечено фраз: {len(filtered_phrases)}")
        for i, phrase in enumerate(filtered_phrases[:5], 1):
            logger.info(f"   {i}. {phrase[:80]}...")

        return filtered_phrases[:15]

    def _is_too_general(self, phrase: str) -> bool:
        """ Проверка на общие фразы """
        general_phrases = {
            'опыт работы', 'функциональные обязанности', 'должностные обязанности',
            'ключевые навыки', 'профессиональные навыки', 'личные качества',
            'образование', 'навыки', 'резюме', 'ищу работу', 'трудоустройство',
            'занятость', 'график работы', 'желательное время в пути'
        }

        phrase_lower = phrase.lower()
        return any(general in phrase_lower for general in general_phrases)

    def _search_by_word_combinations(self, cursor, phrases: List[str], limit: int) -> List[dict]:
        """ Поиск по комбинациям слов """
        all_words = []
        for phrase in phrases:
            words = re.findall(r'\w{4,}', phrase.lower())
            all_words.extend(words)

        stop_words = {
            'менеджер', 'продажам', 'работы', 'клиентами', 'проект', 'компании',
            'организация', 'управление', 'контроль', 'разработка', 'сопровождение'
        }
        unique_words = [word for word in set(all_words) if word not in stop_words]

        if len(unique_words) < 2:
            return []

        logger.info(f"🔍 Поиск по комбинациям слов: {unique_words[:5]}")

        try:
            search_query = ' OR '.join(unique_words[:3])
            cursor.execute('''
                        SELECT filename, candidate_name, content
                        FROM pdf_index_fts 
                        WHERE pdf_index_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    ''', (search_query, limit * 2))

            results = []
            for row in cursor.fetchall():
                content_lower = row['content'].lower()
                matched_count = sum(1 for word in unique_words[:3] if word in content_lower)

                if matched_count >= 2:
                    relevance = min(matched_count / len(unique_words[:3]), 0.6)
                    results.append({
                        'filename': row['filename'],
                        'candidate_name': row['candidate_name'],
                        'file_path': os.path.join(RESUMES_FOLDER, row['filename']),
                        'relevance_score': relevance,
                        'has_exact_match': False,
                        'matched_words': matched_count
                    })

            return results

        except Exception as e:
            logger.error(f"❌ Ошибка поиска по комбинациям слов: {e}")
            return []

    def _fallback_search(self, search_text: str, limit: int = 20):
        """ Резервный поиск по отдельным словам """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                words = re.findall(r'\b\w{4,}\b', search_text.lower())
                stop_words = {'опыт', 'работы', 'работа', 'компания', 'проект'}
                unique_words = [word for word in set(words) if word not in stop_words]

                if not unique_words:
                    unique_words = words[:3]

                logger.info(f"🔄 Fallback поиск по словам: {unique_words}")

                all_results = []
                for word in unique_words[:3]:
                    cursor.execute('''
                        SELECT filename, candidate_name, content
                        FROM pdf_index 
                        WHERE content LIKE ? 
                        LIMIT ?
                    ''', (f'%{word}%', limit))

                    for row in cursor.fetchall():
                        all_results.append({
                            'filename': row['filename'],
                            'candidate_name': row['candidate_name'],
                            'file_path': os.path.join(RESUMES_FOLDER, row['filename']),
                            'relevance_score': 0.3,
                            'has_exact_match': False,
                            'matched_word': word
                        })

                seen_files = set()
                final_results = []
                for result in all_results:
                    if result['filename'] not in seen_files:
                        seen_files.add(result['filename'])
                        final_results.append(result)

                final_results = final_results[:limit]
                logger.info(f"🔄 Fallback поиск: найдено {len(final_results)} результатов")
                return final_results

        except Exception as e:
            logger.error(f"❌ Ошибка fallback поиска: {e}")
            return []

    def _normalize_search_text(self, text: str) -> str:
        """ Нормализация текста """
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _clean_text(self, text: str) -> str:
        """ Очистка текста """
        if not text:
            return ""
        text = ' '.join(text.split())
        return text[:20000]

    def _get_existing_filenames(self):
        """ Получение списка проиндексированных файлов """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM pdf_index")
        existing_files = {row[0] for row in cursor.fetchall()}
        conn.close()
        return existing_files

    def get_index_stats(self):
        """ Статистика индекса """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pdf_index")
            total_files = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM pdf_index_fts")
            total_fts_files = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(file_size) FROM pdf_index")
            total_size = cursor.fetchone()[0] or 0
            db_file_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        return {
            'total_indexed_files': total_files,
            'total_fts_files': total_fts_files,
            'total_size_mb': total_size / (1024 * 1024),
            'db_size_mb': db_file_size / (1024 * 1024)
        }

    def cleanup_missing_files(self) -> int:
        """ Очистка отсутствующих файлов """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT filename FROM pdf_index")
                indexed_files = [row[0] for row in cursor.fetchall()]

                missing_files = []
                for filename in indexed_files:
                    filepath = os.path.join(RESUMES_FOLDER, filename)
                    if not os.path.exists(filepath):
                        missing_files.append(filename)

                if not missing_files:
                    logger.info("✅ Отсутствующие файлы не найдены")
                    return 0

                batch_size = 100
                total_deleted = 0

                for i in range(0, len(missing_files), batch_size):
                    batch = missing_files[i:i + batch_size]
                    placeholders = ','.join('?' for _ in batch)

                    cursor.execute(
                        f"DELETE FROM pdf_index WHERE filename IN ({placeholders})",
                        batch
                    )

                    cursor.execute(
                        f"DELETE FROM pdf_index_fts WHERE filename IN ({placeholders})",
                        batch
                    )

                    deleted_count = cursor.rowcount
                    total_deleted += deleted_count
                    conn.commit()

                logger.info(f"✅ Удалено {total_deleted} отсутствующих файлов")
                return total_deleted

        except Exception as e:
            logger.error(f"❌ Ошибка очистки файлов: {e}")
            return 0

    def extract_text_from_pdf(self, pdf_path: str, use_cache: bool = True) -> Optional[str]:
        """ Полное извлечение текста из PDF """
        cache_key = pdf_path

        if use_cache and cache_key in self._pdf_texts_cache:
            return self._pdf_texts_cache[cache_key]

        text = ""
        filename = os.path.basename(pdf_path)

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"

        except Exception as e:
            logger.warning(f"⚠️ pdfplumber не смог обработать {filename}, пробуем PyPDF2: {e}")
            try:
                with open(pdf_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    for page_num in range(len(pdf_reader.pages)):
                        page = pdf_reader.pages[page_num]
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"

            except Exception as e2:
                logger.error(f"❌ Ошибка при извлечении текста из {filename}: {e2}")
                return None

        result = text.strip() if text.strip() else None
        if use_cache and result:
            if len(self._pdf_texts_cache) >= self.max_cache_size:
                oldest_key = next(iter(self._pdf_texts_cache))
                del self._pdf_texts_cache[oldest_key]
            self._pdf_texts_cache[cache_key] = result

        return result

    def clear_cache(self):
        """ Очистка кэша """
        self._pdf_texts_cache.clear()
        logger.info("🧹 Кэш очищен")
        return True

    def optimize_database(self):
        """ Оптимизация базы данных для производительности """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA optimize")
                cursor.execute("VACUUM")
                conn.commit()
            logger.info("✅ База данных оптимизирована")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка оптимизации БД: {e}")
            return False


pdf_indexer = OptimizedPDFIndexer()