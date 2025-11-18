from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://Cdmn137:Alexvale.1@mydb.evtovyp.mongodb.net/?appName=mydb")
client = AsyncIOMotorClient(MONGO_URL)
database = client.messaging_app

# Colecciones
users_collection = database.users
messages_collection = database.messages
conversations_collection = database.conversations