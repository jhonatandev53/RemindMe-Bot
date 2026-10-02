import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

class Database:
    def __init__(self):
        self.mongo_uri = os.getenv("MONGO_URI")
        self.client = None
        self.db = None
        self.connect()

    def connect(self):
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client["test"]
            print("✅ ¡Conexión exitosa a MongoDB Atlas!")
        except Exception as e:
            print(f"❌ Error al conectar a MongoDB: {e}")

    def get_collection(self, collection_name):
        return self.db[collection_name]