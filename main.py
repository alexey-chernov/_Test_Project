from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import List
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates
import cachetools
import logging

logger = logging.getLogger(__name__)

# Configurations
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:qwerty123456@172.17.0.3/testdb"

# Initialize Database
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# FastAPI App
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jinja2 Templates
templates = Jinja2Templates(directory="templates")

# Models
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255))

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    text = Column(Text)

# Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class PostCreate(BaseModel):
    text: str

class PostResponse(BaseModel):
    id: int
    text: str

class Token(BaseModel):
    access_token: str
    token_type: str

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Utility Functions
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Create Tables
Base.metadata.create_all(bind=engine)

# Caching
cache = cachetools.TTLCache(maxsize=100, ttl=300)

# Routes
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/signup", response_model=Token)
def signup(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    fake_hashed_password = user.password + "notreallyhashed"
    new_user = User(email=user.email, hashed_password=fake_hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    access_token = create_access_token(data={"sub": str(new_user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or user.hashed_password != form_data.password + "notreallyhashed":
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    print(f"Access token created: {encoded_jwt}")
    return encoded_jwt

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError as e:
        print(f"JWT Error: {e}")
        raise credentials_exception
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

@app.post("/addpost", response_model=PostResponse)
def add_post(post: PostCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if len(post.text.encode('utf-8')) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payload too large")
    new_post = Post(user_id=current_user.id, text=post.text)
    try:
        db.add(new_post)
        db.commit()
        db.refresh(new_post)
        logger.info(f"Post added successfully: {new_post}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding post: {e}")
        raise HTTPException(status_code=500, detail="Failed to add post")
    return new_post

@app.get("/getposts", response_model=List[PostResponse])
def get_posts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cached_posts = cache.get(current_user.id)
    if cached_posts:
        logger.info("Returning cached posts")
        return cached_posts
    try:
        posts = db.query(Post).filter(Post.user_id == current_user.id).all()
        cache[current_user.id] = posts
        logger.info(f"Posts retrieved successfully: {posts}")
    except Exception as e:
        logger.error(f"Error fetching posts: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch posts")
    return posts

@app.delete("/deletepost/{post_id}")
def delete_post(post_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    post = db.query(Post).filter(Post.id == post_id, Post.user_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(post)
    db.commit()
    return {"detail": "Post deleted"}
