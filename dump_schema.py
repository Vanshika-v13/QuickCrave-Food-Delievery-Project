import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv('c:\\Food Chatbot\\.env')

cnx = mysql.connector.connect(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "vanshiv1303"),
    database=os.getenv("DB_NAME", "pandeyji_eatery")
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
