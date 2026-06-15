"""
Run this script to wipe the database and reload all default data.
Usage: python reset_db.py
"""
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'inventory.db')
if os.path.exists(db_path):
    os.remove(db_path)
    print("Existing database removed.")

from app import app, db
with app.app_context():
    db.drop_all()
    db.create_all()

print("Database reset complete — 200 items and 4 default users loaded.")
