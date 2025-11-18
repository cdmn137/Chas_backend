from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://Cdmn137:Alexvale.1@mydb.evtovyp.mongodb.net/?appName=mydb")

# Conexión con PyMongo
client = MongoClient(MONGO_URL, server_api=ServerApi('1'))
database = client.messaging_app

# Colecciones
users_collection = database.users
messages_collection = database.messages
conversations_collection = database.conversations

# Verificar conexión
try:
    client.admin.command('ping')
    print("✅ Conectado a MongoDB!")
except Exception as e:
    print("❌ Error conectando a MongoDB:", e)
