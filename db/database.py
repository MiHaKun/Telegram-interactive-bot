from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./assets/db.sqlite3"

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_size=100, max_overflow=200)
SessionMaker = sessionmaker(bind=engine)

Base = declarative_base()