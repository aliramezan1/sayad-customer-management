"""
Pydantic schemas for request validation and response serialization.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class HolderSchema(BaseModel):
    id: int
    national_id: str
    full_name: str
    relationship: Optional[str] = None
    is_active: int = 1

class CustomerCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150)
    national_id: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    credit_color: Optional[str] = "نامشخص"
    risk_score: Optional[int] = 0

class CustomerUpdate(BaseModel):
    full_name: Optional[str] = None
    national_id: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    credit_color: Optional[str] = None
    risk_score: Optional[int] = None

class ChequeCreate(BaseModel):
    customer_id: int
    sayadi_id: str = Field(..., min_length=16, max_length=16)
    cheque_number: Optional[str] = None
    amount: float = 0.0
    cheque_date: Optional[str] = None
    bank_name: Optional[str] = None
    holder_id: Optional[int] = None
    status: Optional[str] = "pending"
    notes: Optional[str] = None

class ChequeUpdate(BaseModel):
    customer_id: Optional[int] = None
    sayadi_id: Optional[str] = None
    cheque_number: Optional[str] = None
    amount: Optional[float] = None
    cheque_date: Optional[str] = None
    bank_name: Optional[str] = None
    holder_id: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class PasargadInquiryRequest(BaseModel):
    sayadi_id: str = Field(..., min_length=16, max_length=16)
    holder_id: int
    customer_id: Optional[int] = None

class BatchInquiryRequest(BaseModel):
    holder_id: Optional[int] = None
    customer_ids: Optional[List[int]] = None
