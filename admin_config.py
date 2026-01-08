import os
from dotenv import load_dotenv

load_dotenv()

DEFAULT_ADMIN_ID = int(os.getenv('ADMIN_ID', '6871129746'))
ADMIN_CONTACT = os.getenv('ADMIN_CONTACT', '@elenazenka')

DEFAULT_ACCESS_DAYS = 30
DEFAULT_DAILY_REQUESTS = 10

LOGGING_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
DEFAULT_LOGGING_LEVEL = 'INFO'