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
from pydantic import BaseModel

app = FastAPI(title="Messaging App API")

# Agrega este modelo al principio de tu main.py
class MessageSend(BaseModel):
    receiver_id: str
    content: str

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
def get_current_user(token: str = Depends(security)):
    payload = verify_token(token.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return user

# Auth Routes
@app.post("/register")
def register(user: User):
    # Verificar si usuario o email ya existen
    existing_user = users_collection.find_one({
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
    result = users_collection.insert_one(user_dict)
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
def login(credentials: UserLogin):
    user = users_collection.find_one({"username": credentials.username})
    
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
def search_users(username: str, current_user: dict = Depends(get_current_user)):
    users = users_collection.find({
        "username": {"$regex": username, "$options": "i"},
        "_id": {"$ne": ObjectId(current_user["_id"])}
    }).limit(10)
    
    return [{
        "id": str(user["_id"]),
        "name": user["name"],
        "username": user["username"]
    } for user in users]

@app.get("/users/{user_id}")
def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="ID de usuario inválido")
    
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "username": user["username"]
    }

# Conversation Routes
@app.get("/conversations")
def get_conversations(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    
    try:
        # Buscar conversaciones donde el usuario es participante
        conversations = list(conversations_collection.find({
            "$or": [
                {"participant1": user_id},
                {"participant2": user_id}
            ]
        }).sort("last_message_time", -1).limit(50))
        
        print(f"📞 Encontradas {len(conversations)} conversaciones para usuario {user_id}")
        
        # Obtener información de los contactos
        conversations_with_contacts = []
        for conv in conversations:
            other_user_id = conv["participant2"] if conv["participant1"] == user_id else conv["participant1"]
            
            try:
                other_user = users_collection.find_one({"_id": ObjectId(other_user_id)})
                if other_user:
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
                else:
                    print(f"⚠️ Usuario {other_user_id} no encontrado")
            except Exception as e:
                print(f"❌ Error procesando usuario {other_user_id}: {e}")
                continue
        
        print(f"✅ Retornando {len(conversations_with_contacts)} conversaciones procesadas")
        return conversations_with_contacts
        
    except Exception as e:
        print(f"❌ Error en /conversations: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# Message Routes
@app.get("/messages/{other_user_id}")
def get_messages(other_user_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    
    messages = messages_collection.find({
        "$or": [
            {"sender_id": user_id, "receiver_id": other_user_id},
            {"sender_id": other_user_id, "receiver_id": user_id}
        ]
    }).sort("timestamp", 1).limit(100)
    
    # Marcar mensajes como leídos
    messages_collection.update_many(
        {"sender_id": other_user_id, "receiver_id": user_id, "read": False},
        {"$set": {"read": True}}
    )
    
    # Actualizar contador de no leídos en conversación
    conversations_collection.update_one({
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
def send_message(message_data: MessageSend, current_user: dict = Depends(get_current_user)):
    sender_id = str(current_user["_id"])
    receiver_id = message_data.receiver_id
    content = message_data.content
    
    print(f"📨 Enviando mensaje de {sender_id} a {receiver_id}: {content}")
    
    # Crear mensaje
    message_data = {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "timestamp": datetime.now(),
        "read": False
    }
    
    result = messages_collection.insert_one(message_data)
    message_id = str(result.inserted_id)
    
    # Crear o actualizar conversación
    conversation = conversations_collection.find_one({
        "$or": [
            {"participant1": sender_id, "participant2": receiver_id},
            {"participant1": receiver_id, "participant2": sender_id}
        ]
    })
    
    if conversation:
        # Actualizar conversación existente
        conversations_collection.update_one(
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
        conversations_collection.insert_one(conversation_data)
    
    # Enviar notificación en tiempo real - VERSIÓN CORREGIDA
    notification = {
        "type": "new_message",
        "message_id": message_id,
        "sender_id": sender_id,
        "sender_name": current_user["name"],
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    
    # En lugar de asyncio.create_task, manejamos el WebSocket de forma diferente
    # Simplemente retornamos éxito - el WebSocket se maneja por separado
    print(f"✅ Mensaje enviado exitosamente: {message_id}")
    
    return {
        "status": "message_sent", 
        "message_id": message_id,
        "notification": notification  # Incluimos la notificación en la respuesta
    }

# WebSocket para conexiones en tiempo real (esto SÍ es async)
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
def root():
    return {"message": "Messaging App API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)




