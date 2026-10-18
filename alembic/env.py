from logging.config import fileConfig
import os, sys
from sqlalchemy import engine_from_config, pool
from alembic import context
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db import Base
from app import models
config=context.config
if config.config_file_name: fileConfig(config.config_file_name)
target_metadata=Base.metadata
def run_migrations_offline():
    url=os.getenv("DATABASE_URL",config.get_main_option("sqlalchemy.url"))
    context.configure(url=url,target_metadata=target_metadata,literal_binds=True,dialect_opts={"paramstyle":"named"},compare_type=True)
    with context.begin_transaction(): context.run_migrations()
def run_migrations_online():
    section=config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"]=os.getenv("DATABASE_URL",section.get("sqlalchemy.url","sqlite:///./bankdq.db"))
    connectable=engine_from_config(section,prefix="sqlalchemy.",poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction(): context.run_migrations()
if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
