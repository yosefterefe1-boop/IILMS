# IILMS — Integrated Inventory Locator and Management System

A web-based warehouse inventory system built with Python and Flask.

---

## Quick Start

### Option A — Double-click (Windows)
1. Double-click **`start.bat`**
2. Wait for the server to start
3. Open your browser and go to **http://127.0.0.1:5000**

### Option B — Terminal
```bash
pip install -r requirements.txt
python app.py
```
Then open **http://127.0.0.1:5000**

---

## Login Credentials

| Username | Password    | Role    | Access Level                                          |
|----------|-------------|---------|-------------------------------------------------------|
| admin    | admin123    | Admin   | Full access including user management                 |
| manager  | manager123  | Manager | Inventory + alerts + reports (CSV/PDF)                |
| clerk    | clerk123    | Clerk   | Enroll, checkout, and restock items                   |
| sales    | sales123    | Sales   | Search and checkout items only                        |

---

## Features

- **Search** — Find any item by name, SKU, category, or specifications
- **Checkout (Out)** — Record items leaving the warehouse
- **Restock (In)** — Record items arriving into the warehouse
- **Stock Alerts** — Automatic alerts when stock falls to or below the threshold
- **Activity Log** — Full history of every checkout and restock
- **Export** — Download inventory as CSV or PDF (manager/admin)
- **User Management** — Create and delete user accounts (admin only)

---

## Resetting the Database

If you want to wipe all data and start fresh:

```bash
python reset_db.py
```

This recreates the database with all 200 default items and the four default users.

---

## Requirements

- Python 3.8 or higher
- See `requirements.txt` for packages
