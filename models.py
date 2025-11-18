from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from bson import ObjectId

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

class User(BaseModel):
    name: str
    username: str
    email: EmailStr
    password: str
    created_at: datetime = datetime.now()

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    name: str
    username: str
    email: str
    created_at: datetime

class Message(BaseModel):
    sender_id: str
    receiver_id: str
    content: str
    timestamp: datetime = datetime.now()
    read: bool = False

class Conversation(BaseModel):
    participant1: str
    participant2: str
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None
    unread_count: int = 0