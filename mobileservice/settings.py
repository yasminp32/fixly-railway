# import os
# from pathlib import Path
# from urllib.parse import urlparse
# from dotenv import load_dotenv
# from django.contrib.auth import get_user_model
# from corsheaders.defaults import default_headers, default_methods

# load_dotenv()


# BASE_DIR = Path(__file__).resolve().parent.parent
# load_dotenv(os.path.join(BASE_DIR, ".env"))
# SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-dev-secret-key")

# def env_bool(name: str, default: bool = False) -> bool:
#     v = os.getenv(name)
#     if v is None:
#         return default
#     return v.strip().lower() in {"1", "true", "yes", "y", "on"}


# DEBUG = env_bool("DEBUG", False)
# #SECRET_KEY = os.environ["SECRET_KEY"]
# #DEBUG = False
# #ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# ALLOWED_HOSTS = [
#     "127.0.0.1", "localhost",
#     ".onrender.com",
# ]

# CORS_ALLOW_CREDENTIALS = True
# CORS_ALLOWED_ORIGINS = [
#     "https://uncollusive-attingent-lupita.ngrok-free.dev",
# ]

# CORS_ALLOWED_ORIGIN_REGEXES = [
#     r"^http://localhost:\d+$",
#     r"^http://127\.0\.0\.1:\d+$",
#     r"^https://.*\.ngrok-free\.app$",
#     r"^https://.*\.ngrok\.io$",
#     r"^https://.*\.ngrok-free\.dev$",
# ]

# CORS_ALLOW_HEADERS = list(default_headers) + [
#     "authorization",
# ]

# CORS_ALLOW_METHODS = list(default_methods)

# CSRF_TRUSTED_ORIGINS = [
#     "http://localhost",
#     "http://127.0.0.1",
#     "https://*.ngrok-free.app",
#     "https://*.ngrok.io",
#     "https://*.ngrok-free.dev",
    
# ]


# #print("LOADED ALLOWED_HOSTS =", ALLOWED_HOSTS)
# LOGIN_REDIRECT_URL = "/api/"
# LOGOUT_REDIRECT_URL = "/api/"

# INSTALLED_APPS = [
#     "django.contrib.admin",
#     "django.contrib.auth",
#     "django.contrib.contenttypes",
#     "django.contrib.sessions",
#     "django.contrib.messages",
#     "django.contrib.staticfiles",
#     "rest_framework",
#     "rest_framework.authtoken",
#     "core",
#     "zoho_integration",
#     "expenses",
#     "corsheaders",
#     'drf_spectacular',
# ]

# MIDDLEWARE = [
#     "corsheaders.middleware.CorsMiddleware",
#     "django.middleware.security.SecurityMiddleware",
#     "whitenoise.middleware.WhiteNoiseMiddleware",
#     "django.contrib.sessions.middleware.SessionMiddleware",
#     "django.middleware.common.CommonMiddleware",
#     "django.middleware.csrf.CsrfViewMiddleware",
#     "django.contrib.auth.middleware.AuthenticationMiddleware",
#     "django.contrib.messages.middleware.MessageMiddleware",
#     "django.middleware.clickjacking.XFrameOptionsMiddleware",
# ]

# ROOT_URLCONF = "mobileservice.urls"

# TEMPLATES = [
#     {
#         "BACKEND": "django.template.backends.django.DjangoTemplates",
#         "DIRS": [BASE_DIR / "templates"],
#         "APP_DIRS": True,
#         "OPTIONS": {
#             "context_processors": [
#                 "django.template.context_processors.debug",
#                 "django.template.context_processors.request",
#                 "django.contrib.auth.context_processors.auth",
#                 "django.contrib.messages.context_processors.messages",
#             ],
#         },
#     },
# ]

# WSGI_APPLICATION = "mobileservice.wsgi.application"

# # Database (expects a DATABASE_URL like postgresql://user:pass@host:5432/dbname)
# def parse_db_url(url):
#     if not url:
#         return None
#     u = urlparse(url)
#     return {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": u.path.lstrip("/"),
#         "USER": u.username or "",
#         "PASSWORD": u.password or "",
#         "HOST": u.hostname or "localhost",
#         "PORT": str(u.port or 5432),
#     }

# DATABASES = {
#     "default": parse_db_url(os.getenv("DATABASE_URL")) or {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": "mobileshopdb",
#         "USER": "postgres",
#         "PASSWORD": "4921",
#         "HOST": "localhost",
#         "PORT": "5432",
#     }
# }

# AUTH_PASSWORD_VALIDATORS = [
#     {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
#     {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
#     {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
#     {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
# ]

# LANGUAGE_CODE = "en-us"
# TIME_ZONE = "UTC"
# USE_I18N = True
# USE_TZ = True
# STATIC_ROOT = BASE_DIR / "staticfiles"
# STATIC_URL = "static/"
# STATICFILES_DIRS = [
#     BASE_DIR / "static",
# ]
# MEDIA_URL = "/media/"
# MEDIA_ROOT = BASE_DIR / "media"
# DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REST_FRAMEWORK = {
#     "DEFAULT_AUTHENTICATION_CLASSES": [
#         "rest_framework.authentication.SessionAuthentication",
#         "rest_framework.authentication.TokenAuthentication",
#         "rest_framework_simplejwt.authentication.JWTAuthentication",
#     ],
#     "DEFAULT_PERMISSION_CLASSES": [
        
#         "rest_framework.permissions.IsAuthenticated",
#     ],
#     'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',  
# }
# SPECTACULAR_SETTINGS = {
#     'TITLE': 'Fixly API',
#     'DESCRIPTION': 'Fixly Mobile Service Backend API',
#     'VERSION': '1.0.0',
# }
# # Auto-assign settings
# ASSIGN_RADIUS_KM = float(os.getenv("ASSIGN_RADIUS_KM", "25"))
# GEO_COUNTRY = os.getenv("GEO_COUNTRY", "IN")

# SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()

# if SENDGRID_API_KEY:
#     INSTALLED_APPS += ["anymail"]
#     EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
#     ANYMAIL = {
#         "SENDGRID_API_KEY": SENDGRID_API_KEY,
#     }
# else:
#     EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
#     EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
#     EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
#     EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
#     EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)

# EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
# EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")  # use an App Password for Gmail
# EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))

# DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER
# SERVER_EMAIL = DEFAULT_FROM_EMAIL
# FRONTEND_RESET_URL = os.getenv("FRONTEND_RESET_URL", "http://localhost:8000/reset-password")
# # =========================
# # ZOHO BOOKS CONFIGURATION
# # =========================

# ZOHO_AUTH_BASE_URL = os.getenv("ZOHO_AUTH_BASE_URL", "https://accounts.zoho.in/oauth/v2")
# ZOHO_BOOKS_BASE_URL = os.getenv("ZOHO_BOOKS_BASE_URL", "https://www.zohoapis.in/books/v3")
# ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
# ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
# ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI")
# ZOHO_BOOKS_ORGANIZATION_ID = os.getenv("ZOHO_BOOKS_ORGANIZATION_ID","60059687124")

# ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
# ZOHO_BOOKS_ACCESS_TOKEN = os.getenv("ZOHO_BOOKS_ACCESS_TOKEN")



# ZOHO_PURCHASE_ACCOUNT_ID = os.getenv("ZOHO_PURCHASE_ACCOUNT_ID")
# ZOHO_SALES_ACCOUNT_ID = os.getenv("ZOHO_SALES_ACCOUNT_ID", "")
# ZOHO_SERVICE_INCOME_ACCOUNT_ID = os.getenv("ZOHO_SERVICE_INCOME_ACCOUNT_ID", "")
# ZOHO_COGS_ACCOUNT_ID = os.getenv("ZOHO_COGS_ACCOUNT_ID", "")
# ZOHO_OTHER_INCOME_ACCOUNT_ID = os.getenv("ZOHO_OTHER_INCOME_ACCOUNT_ID", "")

# from datetime import timedelta

# SIMPLE_JWT = {
#     "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),   # 🔥 Change here
#     "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
# }
# COMPANY_STATE = "Kerala"
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
# CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")

# CELERY_ACCEPT_CONTENT = ["json"]
# CELERY_TASK_SERIALIZER = "json"
# CELERY_RESULT_SERIALIZER = "json"

# CELERY_TIMEZONE = "Asia/Dubai"
# import os
# from pathlib import Path
# from urllib.parse import urlparse
# from dotenv import load_dotenv
# from django.contrib.auth import get_user_model
# from corsheaders.defaults import default_headers, default_methods

# load_dotenv()


# BASE_DIR = Path(__file__).resolve().parent.parent
# load_dotenv(os.path.join(BASE_DIR, ".env"))
# SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-dev-secret-key")

# def env_bool(name: str, default: bool = False) -> bool:
#     v = os.getenv(name)
#     if v is None:
#         return default
#     return v.strip().lower() in {"1", "true", "yes", "y", "on"}


# DEBUG = env_bool("DEBUG", False)
# #SECRET_KEY = os.environ["SECRET_KEY"]
# #DEBUG = False
# #ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# ALLOWED_HOSTS = [
#     "3.108.191.73", "localhost",
#     ".onrender.com",
# ]

# CORS_ALLOW_CREDENTIALS = True
# CORS_ALLOWED_ORIGINS = [
#     "https://uncollusive-attingent-lupita.ngrok-free.dev",
#      "http://localhost:5173",
#      "http://127.0.0.1:5173",
#      "https://fixly-frontend-psi.vercel.app",
# ]

# CORS_ALLOWED_ORIGIN_REGEXES = [
#     r"^http://localhost:\d+$",
#     r"^http://127\.0\.0\.1:\d+$",
#     r"^https://.*\.ngrok-free\.app$",
#     r"^https://.*\.ngrok\.io$",
#     r"^https://.*\.ngrok-free\.dev$",
#     r"^http://localhost:\d+$",
# ]

# CORS_ALLOW_HEADERS = list(default_headers) + [
#     "authorization",
# ]

# CORS_ALLOW_METHODS = list(default_methods)

# CSRF_TRUSTED_ORIGINS = [
#    "http://localhost:5173",
#     "http://127.0.0.1:5173",
#     "http://localhost",
#     "http://127.0.0.1",
#     "https://fixly-frontend-psi.vercel.app"
# ]


# #print("LOADED ALLOWED_HOSTS =", ALLOWED_HOSTS)
# LOGIN_REDIRECT_URL = "/api/"
# LOGOUT_REDIRECT_URL = "/api/"

# INSTALLED_APPS = [
#     "django.contrib.admin",
#     "django.contrib.auth",
#     "django.contrib.contenttypes",
#     "django.contrib.sessions",
#     "django.contrib.messages",
#     "django.contrib.staticfiles",
#     "rest_framework",
#     "rest_framework.authtoken",
#     "core",
#     "zoho_integration",
#     "expenses",
#     "corsheaders",
#     'drf_spectacular',
# ]

# MIDDLEWARE = [
#     "corsheaders.middleware.CorsMiddleware",
#     "django.middleware.security.SecurityMiddleware",
#     "whitenoise.middleware.WhiteNoiseMiddleware",
#     "django.contrib.sessions.middleware.SessionMiddleware",
#     "django.middleware.common.CommonMiddleware",
#     "django.middleware.csrf.CsrfViewMiddleware",
#     "django.contrib.auth.middleware.AuthenticationMiddleware",
#     "django.contrib.messages.middleware.MessageMiddleware",
#     "django.middleware.clickjacking.XFrameOptionsMiddleware",
# ]

# ROOT_URLCONF = "mobileservice.urls"

# TEMPLATES = [
#     {
#         "BACKEND": "django.template.backends.django.DjangoTemplates",
#         "DIRS": [BASE_DIR / "templates"],
#         "APP_DIRS": True,
#         "OPTIONS": {
#             "context_processors": [
#                 "django.template.context_processors.debug",
#                 "django.template.context_processors.request",
#                 "django.contrib.auth.context_processors.auth",
#                 "django.contrib.messages.context_processors.messages",
#             ],
#         },
#     },
# ]

# WSGI_APPLICATION = "mobileservice.wsgi.application"

# # Database (expects a DATABASE_URL like postgresql://user:pass@host:5432/dbname)
# def parse_db_url(url):
#     if not url:
#         return None
#     u = urlparse(url)
#     return {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": u.path.lstrip("/"),
#         "USER": u.username or "",
#         "PASSWORD": u.password or "",
#         "HOST": u.hostname or "localhost",
#         "PORT": str(u.port or 5432),
#     }

# DATABASES = {
#     "default": parse_db_url(os.getenv("DATABASE_URL")) or {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": "mobileshopdb",
#         "USER": "postgres",
#         "PASSWORD": "4921",
#         "HOST": "localhost",
#         "PORT": "5432",
#     }
# }

# AUTH_PASSWORD_VALIDATORS = [
#     {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
#     {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
#     {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
#     {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
# ]

# LANGUAGE_CODE = "en-us"
# TIME_ZONE = "UTC"
# USE_I18N = True
# USE_TZ = True
# STATIC_ROOT = BASE_DIR / "staticfiles"
# STATIC_URL = "static/"
# STATICFILES_DIRS = [
#     BASE_DIR / "static",
# ]
# MEDIA_URL = "/media/"
# MEDIA_ROOT = BASE_DIR / "media"
# DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REST_FRAMEWORK = {
#     "DEFAULT_AUTHENTICATION_CLASSES": [
#         "rest_framework.authentication.SessionAuthentication",
#         "rest_framework.authentication.TokenAuthentication",
#         "rest_framework_simplejwt.authentication.JWTAuthentication",
#     ],
#     "DEFAULT_PERMISSION_CLASSES": [
#         "rest_framework.permissions.IsAuthenticated",
#     ],
#     'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
# }
# SPECTACULAR_SETTINGS = {
#     'TITLE': 'Fixly API',
#     'DESCRIPTION': 'Fixly Mobile Service Backend API',
#     'VERSION': '1.0.0',
# }
# # Auto-assign settings
# ASSIGN_RADIUS_KM = float(os.getenv("ASSIGN_RADIUS_KM", "25"))
# GEO_COUNTRY = os.getenv("GEO_COUNTRY", "IN")

# SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()

# if SENDGRID_API_KEY:
#     INSTALLED_APPS += ["anymail"]
#     EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
#     ANYMAIL = {
#         "SENDGRID_API_KEY": SENDGRID_API_KEY,
#     }
# else:
#     EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
#     EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
#     EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
#     EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
#     EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)

# EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
# EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")  # use an App Password for Gmail
# EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))

# DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER
# SERVER_EMAIL = DEFAULT_FROM_EMAIL
# FRONTEND_RESET_URL = os.getenv("FRONTEND_RESET_URL", "http://localhost:8000/reset-password")
# # =========================
# # ZOHO BOOKS CONFIGURATION
# # =========================

# ZOHO_AUTH_BASE_URL = os.getenv("ZOHO_AUTH_BASE_URL", "https://accounts.zoho.in/oauth/v2")
# ZOHO_BOOKS_BASE_URL = os.getenv("ZOHO_BOOKS_BASE_URL", "https://www.zohoapis.in/books/v3")
# ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
# ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
# ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI")
# ZOHO_BOOKS_ORGANIZATION_ID = os.getenv("ZOHO_BOOKS_ORGANIZATION_ID","60059687124")

# ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
# ZOHO_BOOKS_ACCESS_TOKEN = os.getenv("ZOHO_BOOKS_ACCESS_TOKEN")



# ZOHO_PURCHASE_ACCOUNT_ID = os.getenv("ZOHO_PURCHASE_ACCOUNT_ID")
# ZOHO_SALES_ACCOUNT_ID = os.getenv("ZOHO_SALES_ACCOUNT_ID", "")
# ZOHO_SERVICE_INCOME_ACCOUNT_ID = os.getenv("ZOHO_SERVICE_INCOME_ACCOUNT_ID", "")
# ZOHO_COGS_ACCOUNT_ID = os.getenv("ZOHO_COGS_ACCOUNT_ID", "")
# ZOHO_OTHER_INCOME_ACCOUNT_ID = os.getenv("ZOHO_OTHER_INCOME_ACCOUNT_ID", "")

# from datetime import timedelta

# SIMPLE_JWT = {
#     "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),   # 🔥 Change here
#     "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
# }
# COMPANY_STATE = "Kerala"
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
# CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")

# CELERY_ACCEPT_CONTENT = ["json"]
# CELERY_TASK_SERIALIZER = "json"
# CELERY_RESULT_SERIALIZER = "json"

# CELERY_TIMEZONE = "Asia/Dubai"
# ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from django.contrib.auth import get_user_model
from corsheaders.defaults import default_headers, default_methods

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))
SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-dev-secret-key")

def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


DEBUG = env_bool("DEBUG", False)
#SECRET_KEY = os.environ["SECRET_KEY"]
#DEBUG = False
#ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
ALLOWED_HOSTS = [
    "api.kannottil.com",
    "kannottil.com",
    "www.kannottil.com",
]

def env_list(name: str) -> list:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]

# Extra hosts from env (comma-separated), plus Railway's public domain when deployed there
ALLOWED_HOSTS += env_list("ALLOWED_HOSTS")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN")
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
     "https://kannottil.com",
     "https://www.kannottil.com",
] + env_list("CORS_ALLOWED_ORIGINS")

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
    r"^https://.*\.ngrok-free\.app$",
    r"^https://.*\.ngrok\.io$",
    r"^https://.*\.ngrok-free\.dev$",
    r"^http://localhost:\d+$",
]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "authorization",
]

CORS_ALLOW_METHODS = list(default_methods)

CSRF_TRUSTED_ORIGINS = [
   "https://kannottil.com",
   "https://www.kannottil.com",
   "https://api.kannottil.com",
    "http://127.0.0.1",
] + env_list("CSRF_TRUSTED_ORIGINS")
if RAILWAY_PUBLIC_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RAILWAY_PUBLIC_DOMAIN}")


#print("LOADED ALLOWED_HOSTS =", ALLOWED_HOSTS)
LOGIN_REDIRECT_URL = "/api/"
LOGOUT_REDIRECT_URL = "/api/"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "core",
    "zoho_integration",
    "expenses",
    "corsheaders",
    'drf_spectacular',
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mobileservice.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "mobileservice.wsgi.application"

# Database (expects a DATABASE_URL like postgresql://user:pass@host:5432/dbname)
def parse_db_url(url):
    if not url:
        return None
    u = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username or "",
        "PASSWORD": u.password or "",
        "HOST": u.hostname or "localhost",
        "PORT": str(u.port or 5432),
    }

DATABASES = {
    "default": parse_db_url(os.getenv("DATABASE_URL")) or {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "mobileshopdb",
        "USER": "postgres",
        "PASSWORD": "4921",
        "HOST": "localhost",
        "PORT": "5432",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_URL = "static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'Fixly API',
    'DESCRIPTION': 'Fixly Mobile Service Backend API',
    'VERSION': '1.0.0',
}
# Auto-assign settings
ASSIGN_RADIUS_KM = float(os.getenv("ASSIGN_RADIUS_KM", "25"))
GEO_COUNTRY = os.getenv("GEO_COUNTRY", "IN")

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()

if SENDGRID_API_KEY:
    INSTALLED_APPS += ["anymail"]
    EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
    ANYMAIL = {
        "SENDGRID_API_KEY": SENDGRID_API_KEY,
    }
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")  # use an App Password for Gmail
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER
SERVER_EMAIL = DEFAULT_FROM_EMAIL
FRONTEND_RESET_URL = os.getenv("FRONTEND_RESET_URL", "https://api.kannottil.com/reset-password")
# =========================
# ZOHO BOOKS CONFIGURATION
# =========================

ZOHO_AUTH_BASE_URL = os.getenv("ZOHO_AUTH_BASE_URL", "https://accounts.zoho.in/oauth/v2")
ZOHO_BOOKS_BASE_URL = os.getenv("ZOHO_BOOKS_BASE_URL", "https://www.zohoapis.in/books/v3")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI")
ZOHO_BOOKS_ORGANIZATION_ID = os.getenv("ZOHO_BOOKS_ORGANIZATION_ID","60059687124")

ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_BOOKS_ACCESS_TOKEN = os.getenv("ZOHO_BOOKS_ACCESS_TOKEN")



ZOHO_PURCHASE_ACCOUNT_ID = os.getenv("ZOHO_PURCHASE_ACCOUNT_ID")
ZOHO_SALES_ACCOUNT_ID = os.getenv("ZOHO_SALES_ACCOUNT_ID", "")
ZOHO_SERVICE_INCOME_ACCOUNT_ID = os.getenv("ZOHO_SERVICE_INCOME_ACCOUNT_ID", "")
ZOHO_COGS_ACCOUNT_ID = os.getenv("ZOHO_COGS_ACCOUNT_ID", "")
ZOHO_OTHER_INCOME_ACCOUNT_ID = os.getenv("ZOHO_OTHER_INCOME_ACCOUNT_ID", "")

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),   # 🔥 Change here
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}
COMPANY_STATE = "Kerala"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

CELERY_TIMEZONE = "Asia/Dubai"
#ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
