"""
Generates sample customers.csv / transactions.csv / orders.csv into
./demo_data/ so you can try the whole platform (upload -> ML scoring ->
RAG indexing -> agent recommendations -> approval flow) without needing
your own merchant data first.

Run:  python seed_demo_data.py
Then upload the three files from the Data tab in the UI, in this order:
customers.csv, transactions.csv, orders.csv.
"""
import csv
import os
import random
import datetime as dt

random.seed(7)
OUT_DIR = os.path.join(os.path.dirname(__file__), "demo_data")
os.makedirs(OUT_DIR, exist_ok=True)

TODAY = dt.date.today()
METHODS = ["upi", "card", "netbanking", "wallet"]
PRODUCTS = ["Wireless Earbuds", "Laptop Bag", "Running Shoes", "Smart Watch", "Yoga Mat", "Desk Lamp"]

N_CUSTOMERS = 60

customers = []
for i in range(1, N_CUSTOMERS + 1):
    purchase_count = random.choice([0, 0, 1, 2, 3, 5, 8, 12])
    avg_order = round(random.uniform(500, 8000), 2) if purchase_count else 0
    total_spent = round(avg_order * purchase_count, 2)
    last_purchase = (TODAY - dt.timedelta(days=random.randint(0, 60))).isoformat() if purchase_count else ""
    customers.append({
        "customer_id": f"C{i:04d}",
        "name": f"Customer {i}",
        "email": f"customer{i}@example.com",
        "purchase_count": purchase_count,
        "avg_order_value": avg_order,
        "total_spent": total_spent,
        "last_purchase_date": last_purchase,
        "status": "active",
    })

with open(os.path.join(OUT_DIR, "customers.csv"), "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(customers[0].keys()))
    writer.writeheader()
    writer.writerows(customers)

# Transactions for "today" — includes a deliberate UPI evening failure spike
# and one debited-but-not-confirmed incident, matching the spec's flagship scenario.
transactions = []
txn_counter = 1
for hour in range(0, 24):
    n_this_hour = random.randint(3, 10)
    for _ in range(n_this_hour):
        cust = random.choice(customers)
        method = random.choice(METHODS)
        amount = round(random.uniform(300, 6000), 2)
        if cust["purchase_count"] and random.random() < 0.05:
            amount = round(float(cust["avg_order_value"]) * random.uniform(5, 12), 2)  # anomalous spike

        status = "success"
        if 19 <= hour <= 22 and method == "upi":
            status = random.choices(["success", "failed"], weights=[0.55, 0.45])[0]
        else:
            status = random.choices(["success", "failed"], weights=[0.94, 0.06])[0]

        transactions.append({
            "transaction_id": f"TX{txn_counter:05d}",
            "customer_id": cust["customer_id"],
            "customer_name": cust["name"],
            "amount": amount,
            "payment_method": method,
            "channel": "mobile" if hour >= 18 or hour <= 6 else "desktop",
            "status": status,
            "timestamp": dt.datetime.combine(TODAY, dt.time(hour=hour, minute=random.randint(0, 59))).isoformat(),
        })
        txn_counter += 1

# The flagship "debited but not confirmed" incident
special_customer = customers[0]
transactions.append({
    "transaction_id": "TX1024",
    "customer_id": special_customer["customer_id"],
    "customer_name": special_customer["name"],
    "amount": 10000,
    "payment_method": "upi",
    "channel": "mobile",
    "status": "debited_not_confirmed",
    "timestamp": dt.datetime.combine(TODAY, dt.time(hour=20, minute=15)).isoformat(),
})

with open(os.path.join(OUT_DIR, "transactions.csv"), "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(transactions[0].keys()))
    writer.writeheader()
    writer.writerows(transactions)

# Abandoned-cart orders
orders = []
for i in range(1, 26):
    cust = random.choice(customers)
    orders.append({
        "order_id": f"O{i:04d}",
        "customer_id": cust["customer_id"],
        "transaction_id": "",
        "product_name": random.choice(PRODUCTS),
        "amount": round(random.uniform(500, 15000), 2),
        "status": random.choices(["abandoned", "completed", "pending"], weights=[0.5, 0.3, 0.2])[0],
        "created_at": dt.datetime.combine(TODAY, dt.time(hour=random.randint(0, 23))).isoformat(),
    })

with open(os.path.join(OUT_DIR, "orders.csv"), "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(orders[0].keys()))
    writer.writeheader()
    writer.writerows(orders)

print(f"Demo data written to {OUT_DIR}/ (customers.csv, transactions.csv, orders.csv)")
