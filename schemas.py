"""
Database Schemas for Jewellery Management App

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
- Product -> "product"
- Customer -> "customer"
- Order -> "order"
- Invoice -> "invoice"

These are used for validation in API endpoints and by the database viewer.
"""
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime

class Product(BaseModel):
    sku: str = Field(..., description="Stock keeping unit / unique code")
    name: str = Field(..., description="Product name")
    description: Optional[str] = Field(None, description="Product description")
    category: Optional[str] = Field(None, description="Category like necklace, ring, etc.")
    metal_type: Optional[str] = Field(None, description="Gold plated, silver, etc.")
    stone_type: Optional[str] = Field(None, description="Cubic zirconia, pearls, etc.")
    weight_grams: Optional[float] = Field(None, ge=0, description="Weight in grams")
    stock_qty: int = Field(0, ge=0, description="Quantity in stock")
    unit_price: float = Field(..., ge=0, description="Base price per unit")
    making_charges: float = Field(0, ge=0, description="Making charges per unit")
    tax_rate: float = Field(3.0, ge=0, le=100, description="Tax rate percentage")
    tags: Optional[List[str]] = Field(default=None, description="Search tags")

class Customer(BaseModel):
    name: str = Field(..., description="Customer full name")
    email: Optional[EmailStr] = Field(None, description="Email")
    phone: Optional[str] = Field(None, description="Phone number")
    address: Optional[str] = Field(None, description="Billing/shipping address")

class OrderItem(BaseModel):
    product_id: str = Field(..., description="Reference to product _id")
    sku: str = Field(..., description="Product SKU at time of order")
    name: str = Field(..., description="Product name at time of order")
    qty: int = Field(..., ge=1, description="Quantity ordered")
    unit_price: float = Field(..., ge=0)
    making_charges: float = Field(0, ge=0)
    tax_rate: float = Field(3.0, ge=0, le=100)
    subtotal: float = Field(..., ge=0, description="Calculated: (unit_price+making)*qty")
    tax_amount: float = Field(..., ge=0, description="Calculated: subtotal*tax_rate/100")
    total: float = Field(..., ge=0, description="Calculated: subtotal+tax_amount")

class Order(BaseModel):
    order_number: str = Field(..., description="Human friendly order number")
    customer: Customer
    items: List[OrderItem]
    notes: Optional[str] = None
    status: str = Field("created", description="created, confirmed, fulfilled, cancelled")
    subtotal: float = Field(..., ge=0)
    tax_total: float = Field(..., ge=0)
    grand_total: float = Field(..., ge=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Invoice(BaseModel):
    invoice_number: str = Field(..., description="Invoice number")
    order_id: str = Field(..., description="Order reference id")
    order_number: str = Field(..., description="Order number")
    billed_to: Customer
    items: List[OrderItem]
    subtotal: float
    tax_total: float
    grand_total: float
    issue_date: datetime
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    html: Optional[str] = Field(None, description="Printable HTML content for invoice")
