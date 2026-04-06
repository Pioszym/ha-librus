"""Constants for the Librus Synergia integration."""

DOMAIN = "ha_librus"

# Librus OAuth
LIBRUS_OAUTH_URL = "https://api.librus.pl/OAuth/Authorization"
LIBRUS_OAUTH_2FA_URL = "https://api.librus.pl/OAuth/Authorization/2FA"
LIBRUS_LOGIN_URL = "https://synergia.librus.pl/loguj/portalRodzina"
LIBRUS_CLIENT_ID = 46
LIBRUS_API_BASE = "https://synergia.librus.pl/gateway/api/2.0"

# API endpoints
API_ME = "Me"
API_GRADES = "Grades"
API_SUBJECTS = "Subjects"
API_CATEGORIES = "Grades/Categories"
API_COMMENTS = "Grades/Comments"
API_CLASSES = "Classes"
API_LUCKY_NUMBER = "LuckyNumbers"
API_SCHOOLS = "Schools"
API_TIMETABLES = "Timetables"
API_ATTENDANCES = "Attendances"
API_ANNOUNCEMENTS = "SchoolNotices"
API_TEACHERS = "Users"

# Config
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CHILDREN = "children"

# Defaults
DEFAULT_SCAN_INTERVAL = 15  # minutes
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 120

# Token
TOKEN_LIFETIME = 480  # 8 minutes (actual ~10 min, refresh early)

# Platforms
PLATFORMS = ["sensor"]
