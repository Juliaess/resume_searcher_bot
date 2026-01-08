import os
from dotenv import load_dotenv
from auth import user_manager

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID', '6871129746')

RESUMES_FOLDER = 'data/resumes/'
PDF_INDEX_DB_PATH = 'data/pdf_index.db'
MAX_PDF_RESULTS = 20
PDF_SEARCH_TIMEOUT = 30
PDF_SEARCH_ENABLED = True
REQUIRE_AUTH = True

MAX_CONCURRENT_USERS = 50
MAX_PDF_FILES = 100000
PDF_CACHE_SIZE = 1000
SEARCH_RESULT_LIMIT = 20
MAX_SEARCH_QUERY_LENGTH = 1000
SEARCH_TIMEOUT = 10


def get_logging_level():
    return user_manager.get_system_setting('logging_level', 'INFO')