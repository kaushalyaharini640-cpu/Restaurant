from flask import Flask, render_template, request, redirect, send_file
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, date
import io
import pandas as pd

app = Flask(__name__)

# --- Configure MongoDB ---
client = MongoClient("mongodb+srv://kaushalya09:kaushalya09@cluster0.1axt7iw.mongodb.net/todo")
db = client["restaurant_db"]
menu_col = db["menu"]
orders_col = db["orders"]
tables_col = db["tables"]

# --- Helper: initialize some sample data if collections empty (optional) ---
def init_sample():
    if menu_col.count_documents({}) == 0:
        menu_col.insert_many([
            {"name": "Margherita Pizza", "category": "Pizza", "price": 8.99},
            {"name": "Veggie Burger", "category": "Burger", "price": 6.50},
            {"name": "Caesar Salad", "category": "Salad", "price": 5.00},
            {"name": "Pasta Alfredo", "category": "Pasta", "price": 7.25}
        ])
    if tables_col.count_documents({}) == 0:
        tables_col.insert_many([
            {"table_no": 1, "seats": 2, "available": True},
            {"table_no": 2, "seats": 4, "available": True},
            {"table_no": 3, "seats": 6, "available": True}
        ])
init_sample()

# --- Routes ---
@app.route("/")
def home():
    return render_template("index.html")

# View menu with optional sorting & filtering
@app.route("/menu")
def menu():
    category = request.args.get("category")
    sort = request.args.get("sort")  # e.g., "price_asc" or "price_desc" or "name"
    query = {}
    if category:
        query["category"] = category
    items = list(menu_col.find(query))
    if sort == "price_asc":
        items = sorted(items, key=lambda x: x["price"])
    elif sort == "price_desc":
        items = sorted(items, key=lambda x: x["price"], reverse=True)
    elif sort == "name":
        items = sorted(items, key=lambda x: x["name"])
    # collect categories for filter dropdown
    categories = sorted(list({it["category"] for it in menu_col.find()}))
    return render_template("menu.html", items=items, categories=categories, selected_category=category, sort=sort)

# Place an order
@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        customer = request.form["customer"]
        table_no = int(request.form["table_no"])
        items_selected = request.form.getlist("item")  # list of menu item names
        # build order items list with prices
        order_items = []
        total = 0.0
        for item_name in items_selected:
            it = menu_col.find_one({"name": item_name})
            if it:
                order_items.append({"name": it["name"], "price": it["price"]})
                total += float(it["price"])
        order_doc = {
            "customer": customer,
            "table_no": table_no,
            "items": order_items,
            "total": round(total, 2),
            "status": "Placed",
            "timestamp": datetime.now()
        }
        orders_col.insert_one(order_doc)
        # mark table not available
        tables_col.update_one({"table_no": table_no}, {"$set": {"available": False}})
        return redirect("/menu")
    # GET -> show form
    items = list(menu_col.find())
    tables = list(tables_col.find())
    return render_template("order.html", items=items, tables=tables)

# Reserve a table
@app.route("/reserve", methods=["GET", "POST"])
def reserve():
    if request.method == "POST":
        name = request.form["name"]
        table_no = int(request.form["table_no"])
        date_str = request.form["date"]  # YYYY-MM-DD
        tables_col.update_one(
            {"table_no": table_no},
            {"$set": {"available": False, "reserved_by": name, "reserved_date": date_str}}
        )
        return redirect("/reserve")
    tables = list(tables_col.find())
    return render_template("reserve.html", tables=tables)

# Staff panel to view & update orders/tables
@app.route("/staff", methods=["GET", "POST"])
def staff():
    if request.method == "POST":
        # update order status or table availability
        if "order_id" in request.form:
            oid = request.form["order_id"]
            new_status = request.form["status"]
            orders_col.update_one({"_id": ObjectId(oid)}, {"$set": {"status": new_status}})
        elif "table_no" in request.form:
            table_no = int(request.form["table_no"])
            avail = request.form.get("available") == "on"
            if avail:
                tables_col.update_one(
                    {"table_no": table_no},
                    {"$set": {"available": True}, "$unset": {"reserved_by": "", "reserved_date": ""}}
                )
            else:
                tables_col.update_one({"table_no": table_no}, {"$set": {"available": False}})
        return redirect("/staff")
    # GET -> show orders and tables
    status = request.args.get("status")
    q = {}
    if status:
        q["status"] = status
    orders = list(orders_col.find(q))
    tables = list(tables_col.find())
    return render_template("staff.html", orders=orders, tables=tables, filter_status=status)

# Simple daily sales report CSV download
@app.route("/report", methods=["GET"])
def report():
    day = request.args.get("day")  # YYYY-MM-DD or none => today
    if not day:
        day = date.today().isoformat()
    start = datetime.fromisoformat(day + "T00:00:00")
    end = datetime.fromisoformat(day + "T23:59:59")
    results = list(orders_col.find({"timestamp": {"$gte": start, "$lte": end}}))
    # build dataframe
    rows = []
    for r in results:
        rows.append({
            "order_id": str(r["_id"]),
            "customer": r.get("customer"),
            "table_no": r.get("table_no"),
            "total": r.get("total"),
            "status": r.get("status"),
            "timestamp": r.get("timestamp").isoformat()
        })
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame([{"message": "No orders for this day"}])
    # convert to CSV in-memory
    csv_io = io.StringIO()
    df.to_csv(csv_io, index=False)
    mem = io.BytesIO()
    mem.write(csv_io.getvalue().encode("utf-8"))
    mem.seek(0)
    filename = f"sales_report_{day}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)

if __name__ == "__main__":
    app.run(debug=True)
