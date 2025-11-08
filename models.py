# models.py - SQLAlchemy models for UID server
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class UIDEntry(Base):
    __tablename__ = 'uids'
    id = Column(Integer, primary_key=True)
    uid = Column(String(255), unique=True, nullable=False, index=True)
    meta = Column(Text, default="")
    banned = Column(Boolean, default=False)
    paused = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

def init_db(db_url="sqlite:///uids.db"):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()
