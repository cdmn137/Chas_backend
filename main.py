from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from database import users_collection, messages_collection, conversations_collection
from models import User, UserLogin, UserResponse, Message, Conversation
from auth import hash_password, verify_password, create_access_token, verify_token
from bson import ObjectId
import json
from datetime import datetime
from typing import List

app = FastAPI(title="Messaging App API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especifica tu dominio de Netlify
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
    
    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
    
    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(message)
            except:
                self.disconnect(user_id)
    
    async def broadcast(self, message: str):
        disconnected = []
        for user_id, connection in self.active_connections.items():
            try:
                await connection.send_text(message)
            except:
                disconnected.append(user_id)
        
        for user_id in disconnected:
            self.disconnect(user_id)

manager = ConnectionManager()

# Dependency para obtener usuario actual
async def get_current_user(token: str = Depends(security)):
    payload = verify_token(token.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return user

# Auth Routes
@app.post("/register")
async def register(user: User):
    # Verificar si usuario o email ya existen
    existing_user = await users_collection.find_one({
        "$or": [
            {"username": user.username},
            {"email": user.email}
        ]
    })
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Usuario o email ya existen")
    
    # Hashear contraseña
    hashed_password = hash_password(user.password)
    user_dict = user.dict()
    user_dict["password"] = hashed_password
    
    # Insertar usuario
    result = await users_collection.insert_one(user_dict)
    user_id = str(result.inserted_id)
    
    # Crear token
    token = create_access_token({"user_id": user_id})
    
    return {
        "message": "Usuario creado exitosamente",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "name": user.name,
            "username": user.username,
            "email": user.email
        }
    }

@app.post("/login")
async def login(credentials: UserLogin):
    user = await users_collection.find_one({"username": credentials.username})
    
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    
    # Crear token
    token = create_access_token({"user_id": str(user["_id"])})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user["_id"]),
            "name": user["name"],
            "username": user["username"],
            "email": user["email"]
        }
    }

# User Routes
@app.get("/users/search/{username}")
async def search_users(username: str, current_user: dict = Depends(get_current_user)):
    users = await users_collection.find({
        "username": {"$regex": username, "$options": "i"},
        "_id": {"$ne": ObjectId(current_user["_id"])}
    }).to_list(length=10)
    
    return [{
        "id": str(user["_id"]),
        "name": user["name"],
        "username": user["username"]
    } for user in users]

@app.get("/users/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="ID de usuario inválido")
    
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "username": user["username"]
    }

# Conversation Routes
@app.get("/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    
    # Buscar conversaciones donde el usuario es participante
    conversations = await conversations_collection.find({
        "$or": [
            {"participant1": user_id},
            {"participant2": user_id}
        ]
    }).sort("last_message_time", -1).to_list(length=50)
    
    # Obtener información de los contactos
    conversations_with_contacts = []
    for conv in conversations:
        other_user_id = conv["participant2"] if conv["participant1"] == user_id else conv["participant1"]
        other_user = await users_collection.find_one({"_id": ObjectId(other_user_id)})
        
        conversations_with_contacts.append({
            "conversation_id": str(conv["_id"]),
            "other_user": {
                "id": other_user_id,
                "name": other_user["name"],
                "username": other_user["username"]
            },
            "last_message": conv.get("last_message", ""),
            "last_message_time": conv.get("last_message_time"),
            "unread_count": conv.get("unread_count", 0)
        })
    
    return conversations_with_contacts

# Message Routes
@app.get("/messages/{other_user_id}")
async def get_messages(other_user_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    
    messages = await messages_collection.find({
        "$or": [
            {"sender_id": user_id, "receiver_id": other_user_id},
            {"sender_id": other_user_id, "receiver_id": user_id}
        ]
    }).sort("timestamp", 1).to_list(length=100)
    
    # Marcar mensajes como leídos
    await messages_collection.update_many(
        {"sender_id": other_user_id, "receiver_id": user_id, "read": False},
        {"$set": {"read": True}}
    )
    
    # Actualizar contador de no leídos en conversación
    await conversations_collection.update_one({
        "$or": [
            {"participant1": user_id, "participant2": other_user_id},
            {"participant1": other_user_id, "participant2": user_id}
        ]
    }, {"$set": {"unread_count": 0}})
    
    return [{
        "id": str(msg["_id"]),
        "sender_id": msg["sender_id"],
        "receiver_id": msg["receiver_id"],
        "content": msg["content"],
        "timestamp": msg["timestamp"],
        "read": msg["read"]
    } for msg in messages]

@app.post("/messages/send")
async def send_message(receiver_id: str, content: str, current_user: dict = Depends(get_current_user)):
    sender_id = str(current_user["_id"])
    
    # Crear mensaje
    message_data = {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "timestamp": datetime.now(),
        "read": False
    }
    
    result = await messages_collection.insert_one(message_data)
    message_id = str(result.inserted_id)
    
    # Crear o actualizar conversación
    conversation = await conversations_collection.find_one({
        "$or": [
            {"participant1": sender_id, "participant2": receiver_id},
            {"participant1": receiver_id, "participant2": sender_id}
        ]
    })
    
    if conversation:
        # Actualizar conversación existente
        await conversations_collection.update_one(
            {"_id": conversation["_id"]},
            {
                "$set": {
                    "last_message": content,
                    "last_message_time": datetime.now()
                },
                "$inc": {"unread_count": 1}
            }
        )
    else:
        # Crear nueva conversación
        conversation_data = {
            "participant1": sender_id,
            "participant2": receiver_id,
            "last_message": content,
            "last_message_time": datetime.now(),
            "unread_count": 1
        }
        await conversations_collection.insert_one(conversation_data)
    
    # Enviar notificación en tiempo real
    notification = {
        "type": "new_message",
        "message_id": message_id,
        "sender_id": sender_id,
        "sender_name": current_user["name"],
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    
    await manager.send_personal_message(json.dumps(notification), receiver_id)
    
    return {"status": "message_sent", "message_id": message_id}

# WebSocket para conexiones en tiempo real
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        while True:
            # Mantener conexión activa
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)

@app.get("/")
async def root():
    return {"message": "Messaging App API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)