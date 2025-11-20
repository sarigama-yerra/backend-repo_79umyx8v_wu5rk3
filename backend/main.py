import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db
from schemas import Product as ProductSchema, Customer, Order as OrderSchema, OrderItem as OrderItemSchema, Invoice as InvoiceSchema

app = FastAPI(title="Jewellery Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

def to_str_id(doc):
    if not doc:
        return doc
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def calc_item_totals(unit_price: float, making_charges: float, qty: int, tax_rate: float):
    subtotal = (unit_price + making_charges) * qty
    tax_amount = round(subtotal * (tax_rate / 100.0), 2)
    total = round(subtotal + tax_amount, 2)
    return round(subtotal, 2), tax_amount, total


# Health and test
@app.get("/")
def read_root():
    return {"message": "Jewellery Management Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
            except Exception:
                pass
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# Product Endpoints
@app.get("/api/products")
def list_products(q: Optional[str] = Query(default=None, description="Search by SKU or name")):
    query = {}
    if q:
        query = {"$or": [
            {"sku": {"$regex": q, "$options": "i"}},
            {"name": {"$regex": q, "$options": "i"}},
        ]}
    products = list(db["product"].find(query).sort("name", 1))
    return [to_str_id(p) for p in products]


@app.post("/api/products")
def create_product(product: ProductSchema):
    # Ensure SKU uniqueness
    existing = db["product"].find_one({"sku": product.sku})
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    data = product.model_dump()
    now = datetime.now(timezone.utc)
    data.update({"created_at": now, "updated_at": now})
    result = db["product"].insert_one(data)
    created = db["product"].find_one({"_id": result.inserted_id})
    return to_str_id(created)


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    doc = db["product"].find_one({"_id": PyObjectId.validate(product_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return to_str_id(doc)


@app.put("/api/products/{product_id}")
def update_product(product_id: str, product: ProductSchema):
    oid = PyObjectId.validate(product_id)
    # If SKU changed, enforce uniqueness
    existing_by_sku = db["product"].find_one({"sku": product.sku, "_id": {"$ne": oid}})
    if existing_by_sku:
        raise HTTPException(status_code=400, detail="SKU already in use")
    data = product.model_dump()
    data["updated_at"] = datetime.now(timezone.utc)
    res = db["product"].update_one({"_id": oid}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    doc = db["product"].find_one({"_id": oid})
    return to_str_id(doc)


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str):
    res = db["product"].delete_one({"_id": PyObjectId.validate(product_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


# Orders
class CreateOrderItem(BaseModel):
    product_id: str
    qty: int

class CreateOrderRequest(BaseModel):
    customer: Customer
    items: List[CreateOrderItem]
    notes: Optional[str] = None


def generate_order_number():
    count = db["order"].count_documents({}) + 1
    return f"ORD-{count:05d}"


@app.post("/api/orders")
def create_order(payload: CreateOrderRequest):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items in order")

    # Fetch products and compute totals; also validate stock
    order_items: List[OrderItemSchema] = []
    subtotal_total = 0.0
    tax_total = 0.0

    for item in payload.items:
        prod = db["product"].find_one({"_id": PyObjectId.validate(item.product_id)})
        if not prod:
            raise HTTPException(status_code=400, detail=f"Product not found: {item.product_id}")
        if prod.get("stock_qty", 0) < item.qty:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {prod.get('name')}")

        unit_price = float(prod.get("unit_price", 0))
        making = float(prod.get("making_charges", 0))
        tax_rate = float(prod.get("tax_rate", 0))
        subtotal, tax_amount, total = calc_item_totals(unit_price, making, item.qty, tax_rate)
        subtotal_total += subtotal
        tax_total += tax_amount

        order_item = OrderItemSchema(
            product_id=str(prod["_id"]),
            sku=prod.get("sku"),
            name=prod.get("name"),
            qty=item.qty,
            unit_price=unit_price,
            making_charges=making,
            tax_rate=tax_rate,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
        )
        order_items.append(order_item)

    grand_total = round(subtotal_total + tax_total, 2)

    order_number = generate_order_number()
    now = datetime.now(timezone.utc)
    order_doc = OrderSchema(
        order_number=order_number,
        customer=payload.customer,
        items=order_items,
        notes=payload.notes,
        status="created",
        subtotal=round(subtotal_total, 2),
        tax_total=round(tax_total, 2),
        grand_total=grand_total,
        created_at=now,
        updated_at=now,
    ).model_dump()

    result = db["order"].insert_one(order_doc)

    # Reduce stock
    for item in payload.items:
        db["product"].update_one({"_id": PyObjectId.validate(item.product_id)}, {"$inc": {"stock_qty": -item.qty}})

    created = db["order"].find_one({"_id": result.inserted_id})
    return to_str_id(created)


@app.get("/api/orders")
def list_orders():
    orders = list(db["order"].find().sort("created_at", -1))
    return [to_str_id(o) for o in orders]


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    doc = db["order"].find_one({"_id": PyObjectId.validate(order_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")
    return to_str_id(doc)


# Invoice generation
class InvoiceCreateRequest(BaseModel):
    issue_date: Optional[datetime] = None
    due_in_days: Optional[int] = 0
    notes: Optional[str] = None


def generate_invoice_number():
    count = db["invoice"].count_documents({}) + 1
    return f"INV-{count:05d}"


def render_invoice_html(invoice: dict) -> str:
    # Very basic printable HTML for invoice
    items_html = "".join([
        f"<tr><td>{i.get('sku')}</td><td>{i.get('name')}</td><td style='text-align:right'>{i.get('qty')}</td><td style='text-align:right'>{i.get('unit_price'):.2f}</td><td style='text-align:right'>{i.get('making_charges'):.2f}</td><td style='text-align:right'>{i.get('subtotal'):.2f}</td><td style='text-align:right'>{i.get('tax_amount'):.2f}</td><td style='text-align:right'>{i.get('total'):.2f}</td></tr>"
        for i in invoice.get("items", [])
    ])
    html = f"""
    <html>
    <head>
      <meta charset='utf-8' />
      <title>Invoice {invoice.get('invoice_number')}</title>
      <style>
        body {{ font-family: Arial, sans-serif; color:#111; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        table {{ width:100%; border-collapse: collapse; }}
        th, td {{ border:1px solid #ddd; padding:8px; }}
        th {{ background:#f5f5f5; text-align:left; }}
        .right {{ text-align:right; }}
      </style>
    </head>
    <body>
      <div class='container'>
        <h1>Invoice {invoice.get('invoice_number')}</h1>
        <p><strong>Order:</strong> {invoice.get('order_number')}</p>
        <p><strong>Issue Date:</strong> {invoice.get('issue_date')}</p>
        <h3>Bill To</h3>
        <p>{invoice['billed_to'].get('name')}<br/>{invoice['billed_to'].get('email','')}<br/>{invoice['billed_to'].get('phone','')}<br/>{invoice['billed_to'].get('address','')}</p>
        <h3>Items</h3>
        <table>
          <thead>
            <tr><th>SKU</th><th>Name</th><th class='right'>Qty</th><th class='right'>Unit</th><th class='right'>Making</th><th class='right'>Sub</th><th class='right'>Tax</th><th class='right'>Total</th></tr>
          </thead>
          <tbody>
            {items_html}
          </tbody>
        </table>
        <h3 class='right'>Subtotal: {invoice.get('subtotal'):.2f}</h3>
        <h3 class='right'>Tax: {invoice.get('tax_total'):.2f}</h3>
        <h2 class='right'>Grand Total: {invoice.get('grand_total'):.2f}</h2>
        <p>{invoice.get('notes','')}</p>
      </div>
    </body>
    </html>
    """
    return html


@app.post("/api/orders/{order_id}/invoice")
def create_invoice(order_id: str, payload: InvoiceCreateRequest):
    order = db["order"].find_one({"_id": PyObjectId.validate(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    invoice_number = generate_invoice_number()
    issue_date = payload.issue_date or datetime.now(timezone.utc)

    invoice_doc = InvoiceSchema(
        invoice_number=invoice_number,
        order_id=str(order["_id"]),
        order_number=order["order_number"],
        billed_to=order["customer"],
        items=order["items"],
        subtotal=float(order["subtotal"]),
        tax_total=float(order["tax_total"]),
        grand_total=float(order["grand_total"]),
        issue_date=issue_date,
        due_date=(issue_date if not payload.due_in_days else issue_date + timedelta(days=payload.due_in_days)),
        notes=payload.notes,
    ).model_dump()

    # Render HTML and attach
    invoice_doc["html"] = render_invoice_html(invoice_doc)

    res = db["invoice"].insert_one(invoice_doc)
    created = db["invoice"].find_one({"_id": res.inserted_id})
    return to_str_id(created)


@app.get("/api/invoices")
def list_invoices():
    invs = list(db["invoice"].find().sort("issue_date", -1))
    return [to_str_id(i) for i in invs]


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    doc = db["invoice"].find_one({"_id": PyObjectId.validate(invoice_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return to_str_id(doc)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
