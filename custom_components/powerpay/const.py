"""Constants for the PowerPay integration."""

DOMAIN = "powerpay"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SITE_ID = "site_id"
CONF_DEVICE_ID = "device_id"
CONF_OUTLETS = "outlets"

# Firebase configuration for PowerPay
FIREBASE_API_KEY = "AIzaSyAJIGt9onPpun0xIhTnlpL6PX1-Ahm0EPs"
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# PowerPay REST API bases. The web app calls these directly with the Firebase
# ID token (python API: `token` header; fastify report API: Bearer auth).
POWERPAY_API_BASE = "https://api.powerpay.no/api/v1"
POWERPAY_FASTIFY_BASE = "https://api.powerpay.no/report/api"

# Polling intervals (seconds)
SCAN_INTERVAL_ACTIVE = 60
SCAN_INTERVAL_IDLE = 300

# Platforms
PLATFORMS = ["sensor", "binary_sensor", "switch"]

# Default timeout for API calls (seconds)
API_TIMEOUT = 30

# Firebase token refresh buffer (seconds before expiry to refresh)
TOKEN_REFRESH_BUFFER = 300
