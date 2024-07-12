class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    text = Column(Text)

# Схема для створення постів
class PostCreate(BaseModel):
    text: str

# Схема для відповіді з постами
class PostResponse(BaseModel):
    id: int
    text: str

    class Config:
        orm_mode = True