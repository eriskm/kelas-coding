"""Pydantic schemas (request/response models)."""
from datetime import datetime, date
from pydantic import BaseModel, ConfigDict
from typing import Optional, List


# ---------- Customer ----------
class CustomerBase(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- ServiceOrder ----------
class ServiceOrderBase(BaseModel):
    no_servis: str
    customer_id: int
    device: str
    brand: Optional[str] = None
    model: Optional[str] = None
    damagetype: Optional[str] = None
    technician: Optional[str] = None
    status: Optional[str] = "RECEIVED"
    estimate: Optional[float] = 0
    payment: Optional[float] = 0
    service_date: Optional[date] = None


class ServiceOrderCreate(ServiceOrderBase):
    pass


class ServiceOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    device: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    damagetype: Optional[str] = None
    technician: Optional[str] = None
    status: Optional[str] = None
    estimate: Optional[float] = None
    payment: Optional[float] = None


class ServiceOrderOut(ServiceOrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    customer: Optional[CustomerOut] = None


class ServiceOrderList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    no_servis: str
    customer_id: int
    device: str
    brand: Optional[str] = None
    model: Optional[str] = None
    damagetype: Optional[str] = None
    technician: Optional[str] = None
    status: str
    estimate: float
    payment: float
    service_date: Optional[date] = None
    created_at: datetime
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


# ---------- Payment ----------
class PaymentBase(BaseModel):
    service_order_id: int
    amount: float
    method: Optional[str] = "CASH"
    note: Optional[str] = None


class PaymentCreate(PaymentBase):
    pass


class PaymentOut(PaymentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- Dashboard Overview ----------
class OverviewItem(BaseModel):
    label: str
    value: float


class DashboardOverview(BaseModel):
    omset: float
    laba_kotor: float
    total_beban: float
    laba_bersih: float
    target_gaji: float
    insight: List[dict]
    star_cards: List[dict]
