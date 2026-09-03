"""SQLAlchemy models (database tables)."""
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Date,
)
from sqlalchemy.orm import relationship

from database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(30))
    email = Column(String(120))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    service_orders = relationship("ServiceOrder", back_populates="customer")


class ServiceOrder(Base):
    __tablename__ = "service_orders"

    id = Column(Integer, primary_key=True, index=True)
    no_servis = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    device = Column(String(120), nullable=False)
    brand = Column(String(60))
    model = Column(String(60))
    damagetype = Column(String(120))
    technician = Column(String(60))
    status = Column(String(30), default="RECEIVED")
    estimate = Column(Float, default=0)
    payment = Column(Float, default=0)
    service_date = Column(Date, default=datetime.utcnow().date)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="service_orders")
    payments = relationship("Payment", back_populates="service_order", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    service_order_id = Column(Integer, ForeignKey("service_orders.id"), nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String(30), default="CASH")
    note = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    service_order = relationship("ServiceOrder", back_populates="payments")
