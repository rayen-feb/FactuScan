from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, func, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import os
import json

# Database configuration
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '3306')
DB_USER = os.environ.get('DB_USER', 'factuscan_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'secure_password')
DB_NAME = os.environ.get('DB_NAME', 'factuscan')

def get_engine():
    # Try MySQL first (same fallback logic as app.py)
    if DB_HOST != 'localhost' or os.environ.get('MYSQL_URL'):
        try:
            db_uri = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            temp_engine = create_engine(db_uri, pool_pre_ping=True, connect_args={'connect_timeout': 3})
            with temp_engine.connect():
                pass
            return temp_engine
        except:
            pass
    # Fallback to local SQLite
    return create_engine("sqlite:///factuscan.db", connect_args={'check_same_thread': False})

engine = get_engine()
Base = declarative_base()
Session = sessionmaker(bind=engine)

# Database Models
class Invoice(Base):
    __tablename__ = 'invoices'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    filename = Column(String(255))
    invoice_number = Column(String(100))
    invoice_date = Column(String(50))
    supplier = Column(String(255))
    ice = Column(String(50))
    ht_amount = Column(Float)
    vat_amount = Column(Float)
    total_amount = Column(Float)
    extracted_text = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'filename': self.filename,
            'invoice_number': self.invoice_number,
            'invoice_date': self.invoice_date,
            'supplier': self.supplier,
            'ice': self.ice,
            'ht_amount': self.ht_amount,
            'vat_amount': self.vat_amount,
            'total_amount': self.total_amount,
            'extracted_text': self.extracted_text,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Pack(Base):
    __tablename__ = 'packs'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    price_eur = Column(Float)
    price_tnd = Column(Float)
    limit_text = Column(String(100))
    features_json = Column(Text)
    is_featured = Column(Boolean, default=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'price_eur': self.price_eur,
            'price_tnd': self.price_tnd,
            'limit_text': self.limit_text,
            'features': json.loads(self.features_json) if self.features_json else [],
            'is_featured': self.is_featured
        }

class DatabaseManager:
    def __init__(self):
        self.session = Session()
    
    def create_tables(self):
        """Create all database tables"""
        Base.metadata.create_all(engine)
    
    def get_session(self):
        """Get a new database session"""
        return Session()
    
    def save_invoice(self, invoice_data):
        """Save a new invoice to the database"""
        try:
            invoice = Invoice(**invoice_data)
            self.session.add(invoice)
            self.session.commit()
            return invoice.id
        except Exception as e:
            self.session.rollback()
            raise e
    
    def get_invoice(self, invoice_id, user_id=None):
        """Get an invoice by ID"""
        query = self.session.query(Invoice).filter_by(id=invoice_id)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        return query.first()
    
    def get_all_invoices(self, user_id=None):
        """Get all invoices"""
        query = self.session.query(Invoice)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        return query.all()
    
    def update_invoice(self, invoice_id, data, user_id=None):
        """Update an invoice"""
        try:
            query = self.session.query(Invoice).filter_by(id=invoice_id)
            if user_id is not None:
                query = query.filter_by(user_id=user_id)
            invoice = query.first()
            if not invoice:
                return None
            
            for key, value in data.items():
                if hasattr(invoice, key):
                    setattr(invoice, key, value)
            
            invoice.updated_at = datetime.now()
            self.session.commit()
            return invoice
        except Exception as e:
            self.session.rollback()
            raise e
    
    def delete_invoice(self, invoice_id, user_id=None):
        """Delete an invoice"""
        try:
            query = self.session.query(Invoice).filter_by(id=invoice_id)
            if user_id is not None:
                query = query.filter_by(user_id=user_id)
            invoice = query.first()
            if not invoice:
                return False
            
            self.session.delete(invoice)
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            raise e
    
    def get_statistics(self, user_id=None):
        """Get invoice statistics"""
        try:
            query = self.session.query(Invoice)
            if user_id is not None:
                query = query.filter_by(user_id=user_id)
                
            total_invoices = int(query.with_entities(func.count(Invoice.id)).scalar() or 0)
            total_amount = float(query.with_entities(func.coalesce(func.sum(Invoice.total_amount), 0.0)).scalar() or 0.0)
            
            # Current month statistics (SQLite & MySQL compatible)
            today = datetime.now()
            start_of_month = datetime(today.year, today.month, 1)
            
            # Ensure month query respects user filter
            month_query = self.session.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).filter(
                Invoice.created_at >= start_of_month
            )
            # Enforce user boundary for monthly sum
            if user_id is not None:
                month_query = month_query.filter(Invoice.user_id == user_id)
                
            month_amount = float(month_query.scalar() or 0.0)
            
            # Last 7 days trend
            labels, sums = [], []
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                d_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
                d_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
                
                d_query = self.session.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).filter(
                    Invoice.created_at >= d_start, Invoice.created_at <= d_end
                )
                if user_id:
                    d_query = d_query.filter(Invoice.user_id == user_id)
                
                labels.append(day.strftime('%a'))
                sums.append(round(float(d_query.scalar() or 0.0), 2))
            
            # Supplier distribution for the visual components
            supp_query = self.session.query(Invoice.supplier, func.count(Invoice.id)).group_by(Invoice.supplier).all()
            supp_labels = [str(s[0] or "Inconnu") for s in supp_query]
            supp_series = [int(s[1]) for s in supp_query]
            
            return {
                'total_invoices': int(total_invoices),
                'total_amount': float(total_amount),
                'month_amount': float(month_amount),
                'average_amount': float(total_amount) / total_invoices if total_invoices > 0 else 0,
                'chart': {
                    'labels': labels,
                    'sums': sums,
                    'series': [
                        {"name": "Revenu (DT)", "data": sums}
                    ]
                },
                'pie_chart': {
                    'labels': supp_labels,
                    'series': supp_series
                }
            }
        except Exception as e:
            raise e