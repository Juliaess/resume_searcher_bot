import re
import os
from typing import Dict, Any


def extract_name_from_filename(filename: str) -> str:
    """ Извлекает имя кандидата из имени файла """
    try:
        name_without_ext = os.path.splitext(filename)[0]
        name_clean = re.sub(r'[^\w\s]', ' ', name_without_ext)
        name_clean = re.sub(r'\s+', ' ', name_clean).strip()
        return name_clean if name_clean else "Неизвестный кандидат"
    except Exception:
        return "Неизвестный кандидат"


def format_pdf_search_result(result: Dict[str, Any], index: int, total: int) -> str:
    """ Форматирование результата поиска по PDF """
    return (
        f"📄 **Резюме {index}/{total}**\n"
        f"👤 **Кандидат:** {result.get('candidate_name', 'Неизвестно')}\n"
        f"💡 **Найдено по запросу**"
    )


def safe_filename(filename: str) -> str:
    """ Очищает имя файла от опасных символов """
    return re.sub(r'[<>:"/\\|?*]', '', filename)


def get_file_size_mb(file_path: str) -> float:
    """ Получает размер файла в мегабайтах """
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except:
        return 0.0