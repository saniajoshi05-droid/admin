"""Global store settings."""
import os

# Settings which define how your shop looks.
STORE_NAME = "Sania's Website"
PRIMARY_COLOR = '#485fc7'
ACCENT_COLOR = '#ffe08a'

# Credentials for the database, which stores all data such as products and purchases.
DB_HOST = os.environ.get("DB_HOST", 'db.sajo1826.csci3403.com')
DB_USER = os.environ.get("DB_USER", "shop")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "shop")
DB_NAME = os.environ.get("DB_NAME", "shop")

# A secret key which Flask uses to securely sign sessions: Flask handles all of that
# authentication code, so we don't need to deal with how or when this gets used.
SECRET_KEY = os.environ.get("SECRET_KEY", '6f67d4cae02dc00b7505d809c94f23d6bd6b4a118e3ec6fee6b6029e2ba0b641')

