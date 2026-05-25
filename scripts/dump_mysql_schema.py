#!/usr/bin/env python3
"""
MySQL schema dump — migration/dev utility only. Not used at runtime.

Usage:
  python scripts/dump_mysql_schema.py
"""
import mysql.connector
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

cnx = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", 4000)),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
)

cursor = cnx.cursor()
cursor.execute("SHOW TABLES")
tables = cursor.fetchall()

for table in tables:
    table_name = table[0]
    cursor.execute(f"SHOW CREATE TABLE {table_name}")
    create_table = cursor.fetchone()
    print(f"-- Table: {table_name}")
    print(create_table[1])
    print(";" + "\n")

cursor.close()
cnx.close()
