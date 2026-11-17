"""
Datadrix Assessment Platform - MongoDB Table/Collection Helper & Sync Utility
Allows inspecting, querying, and synchronizing candidate discount records with MongoDB.
"""
import os
import sys
from datetime import datetime, timezone
from pymongo import MongoClient

DEFAULT_MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/datadrix_discounts")
DB_NAME = os.getenv("MONGO_DB_NAME", "datadrix_discounts")
COLLECTION_NAME = "candidate_discounts"

def get_client(uri=None):
    target_uri = uri or DEFAULT_MONGO_URI
    client = MongoClient(target_uri, serverSelectionTimeoutMS=2500)
    client.admin.command('ping')
    return client

def inspect_collection(uri=None):
    try:
        client = get_client(uri)
        db = client.get_default_database() or client[DB_NAME]
        coll = db[COLLECTION_NAME]
        
        count = coll.count_documents({})
        print(f"[MongoDB] Connected successfully to '{db.name}.{COLLECTION_NAME}'")
        print(f"[MongoDB] Total discount records found: {count}")
        print("-" * 70)
        
        for doc in coll.find().sort("created_at", -1).limit(10):
            print(f"Name     : {doc.get('name')}")
            print(f"Email    : {doc.get('email')}")
            print(f"Phone    : {doc.get('phone')}")
            print(f"Score    : {doc.get('score')}/{doc.get('max_score', 20)}")
            print(f"Discount : {doc.get('discount_percent')}%")
            print(f"10-PIN   : {doc.get('pin')}")
            print(f"Created  : {doc.get('created_at')}")
            print(f"Expires  : {doc.get('expires_at')}")
            print(f"Status   : {doc.get('status')}")
            print("-" * 70)
    except Exception as e:
        print(f"[MongoDB Error] Could not connect to MongoDB at '{uri or DEFAULT_MONGO_URI}': {e}")
        print("Note: If running MongoDB locally, make sure mongod is running, or set MONGO_URI to your MongoDB Atlas connection string.")

def sync_sqlite_to_mongo():
    from app import create_app
    from app.models.discount import CandidateDiscount
    from app.services.discount_service import sync_record_to_mongo

    app = create_app()
    with app.app_context():
        discounts = CandidateDiscount.query.all()
        print(f"[Sync] Found {len(discounts)} local discount records.")
        synced_count = 0
        for d in discounts:
            if sync_record_to_mongo(d):
                synced_count += 1
        print(f"[Sync] Successfully synchronized {synced_count}/{len(discounts)} records to MongoDB.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        sync_sqlite_to_mongo()
    else:
        inspect_collection()
