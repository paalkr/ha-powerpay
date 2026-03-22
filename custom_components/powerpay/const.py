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

# PowerPay app URLs
POWERPAY_BASE_URL = "https://app.powerpay.no"
POWERPAY_LOGIN_URL = f"{POWERPAY_BASE_URL}/api/login"
POWERPAY_HOME_URL = f"{POWERPAY_BASE_URL}/en/home"

# Polling intervals (seconds)
SCAN_INTERVAL_ACTIVE = 60
SCAN_INTERVAL_IDLE = 300

# Platforms
PLATFORMS = ["sensor", "binary_sensor", "switch"]

# Default timeout for API calls (seconds)
API_TIMEOUT = 30

# Firebase token refresh buffer (seconds before expiry to refresh)
TOKEN_REFRESH_BUFFER = 300
