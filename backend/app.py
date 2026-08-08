import os
import uuid
import json
import io
import base64
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, flash, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user, login_fresh
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from PIL import Image
import pdf2image
import cv2
import numpy as np
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, func, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
# import easyocr # Replaced by PaddleOCR (PP-StructureV3)
# import easyocr # Replaced by , PPStructureV3PaddleOCR (PP-StructureV3)

# Make paddleocr optional so the app starts even if it's not installed
PaddleOCR = None
PPStructureV3 = None
PPStructure = None
try:
    from paddleocr import PaddleOCR
    try:
        from paddleocr import PPStructureV3
    except ImportError:
        PPStructureV3 = None
    try:
        from paddleocr import PPStructure
    except ImportError:
        PPStructure = None
    if PPStructureV3 is None and PPStructure is None:
        print("[WARNING] paddleocr installed but no PPStructure or PPStructureV3 class found.")
except ImportError:
    print("[WARNING] paddleocr not installed. PaddleOCR features will be disabled.")

import re
# import magic  # Commented out - not available on Windows, using fallback detection
from flask_cors import CORS
from dotenv import load_dotenv
import google # Ensure top-level 'google' module is available for traceback formatting
from google.api_core import exceptions # Import exceptions module
import google.generativeai as genai
from flask_socketio import SocketIO, emit

# Load configuration
load_dotenv()

# Autoriser le transport non-sécurisé (HTTP) pour le développement local
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# FINAL-ULTRA-MEGA-ROBUST API KEY DETECTION
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OCR_SPACE_API_KEY = os.environ.get('OCR_SPACE_API_KEY')

# Scan all environment variables if not found
if not GOOGLE_API_KEY or not OCR_SPACE_API_KEY:
    for k, v in os.environ.items():
        if not v or not isinstance(v, str): continue
        k_upper = k.replace(' ', '_').upper()
        v_clean = v.strip().strip('"').strip("'")
        
        if not GOOGLE_API_KEY:
            if ("GOOGLE" in k_upper and "API" in k_upper) or "AIza" in v_clean:
                GOOGLE_API_KEY = v_clean
        
        if not OCR_SPACE_API_KEY:
            if "OCR_SPACE" in k_upper or (len(v_clean) == 15 and v_clean.isalnum() and v_clean.startswith('K')):
                OCR_SPACE_API_KEY = v_clean

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        print(f"[SYSTEM] Gemini IA activée.")
    except Exception as e:
        print(f"[ERROR] failed to configure Gemini: {e}")

if OCR_SPACE_API_KEY:
    print(f"[SYSTEM] OCR.Space activé.")

# Initialize Flask app
# Use absolute paths relative to this file's location (backend/app.py -> .. -> frontend/)
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static')
)

# Middleware pour gérer correctement les en-têtes de proxy (essentiel en production et pour OAuth)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration Google OAuth
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
Base = declarative_base()

class User(Base, UserMixin):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(20), default='user')
    subscription_type = Column(String(50), default='Basic')
    full_name = Column(String(200), nullable=False)
    company_name = Column(String(200))
    city = Column(String(100))
    country = Column(String(100))
    purpose_of_use = Column(String(100))
    additional_info = Column(Text)
    profile_image = Column(String(255), default='default_avatar.png')
    is_authorized = Column(Boolean, default=False)
    email_confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime)

    @property
    def is_active(self):
        return self.is_authorized

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

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now)
    status = Column(String(20), default='new') # "new", "read", "resolved"
    reply = Column(Text)

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

@login_manager.user_loader
def load_user(user_id):
    if not DB_AVAILABLE: return None
    db = get_db()
    return db.get(User, int(user_id)) if db else None

# Decorator to restrict routes to Admins only
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_role = getattr(current_user, 'role', '') or ''
        if not current_user.is_authenticated or user_role.lower() != 'admin':
            flash("Accès refusé. Autorisation administrateur requise.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROFILE_FOLDER'] = os.path.join(app.static_folder, 'uploads', 'profiles')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'factuscan_secure_fallback_key_2024')

# Configuration de la session pour la stabilité OAuth
app.config['SESSION_COOKIE_NAME'] = 'factuscan_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False # Doit être False pour le HTTP local

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_FOLDER'], exist_ok=True)

# Database configuration and connection
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '3306')
DB_USER = os.environ.get('DB_USER', 'factuscan_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'secure_password')
DB_NAME = os.environ.get('DB_NAME', 'factuscan')

# Attempt connection with real test
DB_AVAILABLE = False
engine = None
Session = None

def init_db():
    global DB_AVAILABLE, engine, Session
    # 1. Try MySQL (if not on a localhost default that likely fails)
    if DB_HOST != 'localhost' or os.environ.get('MYSQL_URL'):
        try:
            db_uri = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            temp_engine = create_engine(db_uri, pool_pre_ping=True, connect_args={'connect_timeout': 3})
            with temp_engine.connect() as conn:
                pass
            engine = temp_engine
            Session = sessionmaker(bind=engine)
            DB_AVAILABLE = True
            print("[SUCCESS] MySQL Database connected.")
            return
        except Exception as e:
            print(f"[WARNING] MySQL connection failed ({e}).")

    # 2. Fallback to SQLite
    try:
        db_uri = "sqlite:///factuscan.db"
        engine = create_engine(db_uri, connect_args={'check_same_thread': False})
        Session = sessionmaker(bind=engine)
        with engine.connect() as conn:
            pass
        DB_AVAILABLE = True
        print("[INFO] Using SQLite local database.")
    except Exception as e:
        print(f"[ERROR] All fallbacks failed: {e}")
        DB_AVAILABLE = False

init_db()

# Per-request database session helper
def get_db():
    if not DB_AVAILABLE or not Session:
        return None
    if 'db' not in g:
        g.db = Session()
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Create tables (only if DB is available)
if DB_AVAILABLE:
    try:
        Base.metadata.create_all(engine)
        # Manual migration for existing databases: check and add missing columns
        with engine.connect() as conn:
            from sqlalchemy import inspect, text
            inspector = inspect(engine)
            columns = [c['name'] for c in inspector.get_columns('invoices')]
            
            migration_columns = {
                'ht_amount': 'FLOAT',
                'vat_amount': 'FLOAT',
                'total_amount': 'FLOAT',
                'user_id': 'INTEGER',
                'ice': 'VARCHAR(50)',
                'supplier': 'VARCHAR(255)',
                'created_at': 'DATETIME',
                'updated_at': 'DATETIME'
            }
            
            for col_name, col_type in migration_columns.items():
                if col_name not in columns:
                    print(f"[INFO] Adding missing column '{col_name}' to invoices table...")
                    conn.execute(text(f"ALTER TABLE invoices ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
            
            # Ensure existing records have timestamps and non-null amounts for charts/visuals
            conn.execute(text("UPDATE invoices SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            conn.execute(text("UPDATE invoices SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
            conn.execute(text("UPDATE invoices SET total_amount = 0.0 WHERE total_amount IS NULL"))
            conn.execute(text("UPDATE invoices SET ht_amount = 0.0 WHERE ht_amount IS NULL"))
            conn.execute(text("UPDATE invoices SET vat_amount = 0.0 WHERE vat_amount IS NULL"))
            conn.commit()

            # Manual migration for users table: add profile fields if missing
            user_cols = [c['name'] for c in inspector.get_columns('users')]
            new_user_fields = {
                'full_name': 'VARCHAR(200)',
                'company_name': 'VARCHAR(200)',
                'city': 'VARCHAR(100)',
                'country': 'VARCHAR(100)',
                'purpose_of_use': 'VARCHAR(100)',
                'additional_info': 'TEXT',
                'profile_image': 'VARCHAR(255)',
                'created_at': 'DATETIME',
                'last_login': 'DATETIME',
                'email_confirmed': 'BOOLEAN DEFAULT 0'
            }
            for field, col_type in new_user_fields.items():
                if field not in user_cols:
                    print(f"[INFO] Adding missing column '{field}' to users table...")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {field} {col_type}"))
                    conn.commit()
            
            # Populate created_at for users to show up in distribution visuals
            conn.execute(text("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            conn.commit()

            # Manual migration for messages table: add status if missing
            msg_cols = [c['name'] for c in inspector.get_columns('messages')]
            msg_migrations = {
                'status': "VARCHAR(20) DEFAULT 'new'",
                'reply': "TEXT",
                'timestamp': "DATETIME"
            }
            for field, col_type in msg_migrations.items():
                if field not in msg_cols:
                    print(f"[INFO] Adding missing column '{field}' to messages table...")
                    conn.execute(text(f"ALTER TABLE messages ADD COLUMN {field} {col_type}"))
                    conn.commit()
            
            # Populate timestamp for messages for conversation history
            conn.execute(text("UPDATE messages SET timestamp = CURRENT_TIMESTAMP WHERE timestamp IS NULL"))
            conn.commit()

        # Seed packs if empty
        db_init_session = Session()
        try:
            if db_init_session.query(Pack).count() == 0:
                print("[INFO] Seeding default packs...")
                p1 = Pack(name="Basic", description="Parfait pour les indépendants et petites structures.", price_eur=69.0, price_tnd=150.0, limit_text="200 factures / mois", features_json=json.dumps(["Extraction IA des factures (n°, date, fournisseur, montants)", "Dashboard simple", "Export CSV & PDF"]), is_featured=False)
                p2 = Pack(name="Pro", description="Pour les PME qui veulent aller plus loin.", price_eur=199.0, price_tnd=400.0, limit_text="1 000 factures / mois", features_json=json.dumps(["Extraction IA avancée (lignes produits)", "Dashboard avancé (statistiques HT/TTC)", "Multi-utilisateurs (jusqu'à 5)", "Export CSV & PDF", "Support email prioritaire"]), is_featured=True)
                p3 = Pack(name="Enterprise", description="Solution complète pour les grandes structures.", price_eur=499.0, price_tnd=1000.0, limit_text="Factures illimitées", features_json=json.dumps(["Tout du pack Pro", "IA avancée (validation HT/TTC, détection anomalies)", "Dashboard multi-filiales", "Sécurité renforcée (2FA, chiffrement)", "Support prioritaire 24/7", "Onboarding dédié"]), is_featured=False)
                db_init_session.add_all([p1, p2, p3])
                db_init_session.commit()
        except Exception as seed_e:
            print(f"[WARNING] Seeding failed: {seed_e}")
        finally:
            db_init_session.close()
    except Exception as e:
        print(f"[WARNING] Database initialization/migration error: {e}")

# Disable oneDNN to avoid NotImplementedError on Windows with newer Paddle builds
os.environ['FLAGS_use_mkldnn'] = '0'

# ================================================================
# LAZY PaddleOCR initialization for memory-constrained deploys
# ================================================================
# PaddleOCR downloads and loads several large models (~10MB each) at
# init time. On Render/HuggingFace free tiers (512MB RAM) this caused
# OOM kills (`Exited with status 137`) and the app never bound a port.
#
# Fix: initialize the models LAZILY the first time a scan is requested,
# not at import time. Set EAGER_OCR=1 to restore the old behavior
# (e.g. for local dev where memory is not a concern).
# ================================================================
paddle_ocr_reader = None
pp_structure_analyzer = None
_paddle_init_attempted = False

# Determine the structure class available in this PaddleOCR version
paddle_structure_class = None
if PPStructureV3 is not None:
    paddle_structure_class = PPStructureV3
elif PPStructure is not None:
    paddle_structure_class = PPStructure


def init_paddle_ocr():
    """Initialize PaddleOCR readers lazily (first call) and cache them."""
    global paddle_ocr_reader, pp_structure_analyzer, _paddle_init_attempted
    if _paddle_init_attempted:
        return paddle_ocr_reader is not None or pp_structure_analyzer is not None
    _paddle_init_attempted = True

    # ✅ OCR (text extraction) - Initialize independently for fallback
    if PaddleOCR is not None:
        try:
            paddle_ocr_reader = PaddleOCR(
                lang="fr",
                use_angle_cls=True,  # stable & safe
                show_log=False
            )
            print("[SYSTEM] PaddleOCR reader initialized.")
        except Exception as e:
            print(f"[ERROR] PaddleOCR reader init failed: {e}")
            paddle_ocr_reader = None

    # ✅ Structure (tables/layout) - PPStructureV3 or PPStructure
    if paddle_structure_class is not None:
        structure_lang = "en"
        try:
            pp_structure_analyzer = paddle_structure_class(
                show_log=False,
                lang=structure_lang
            )
            print(f"[SYSTEM] {paddle_structure_class.__name__} initialized successfully with lang='{structure_lang}'.")
        except Exception as e:
            print(f"[WARNING] {paddle_structure_class.__name__} init with lang='{structure_lang}' failed: {e}")
            try:
                pp_structure_analyzer = paddle_structure_class(
                    show_log=False
                )
                print(f"[SYSTEM] {paddle_structure_class.__name__} initialized successfully without explicit lang.")
            except Exception as e2:
                print(f"[ERROR] {paddle_structure_class.__name__} init without lang failed: {e2}")
                pp_structure_analyzer = None
    else:
        print("[WARNING] No paddleocr PPStructureV3 or PPStructure class available for structured OCR.")

    return paddle_ocr_reader is not None or pp_structure_analyzer is not None


# Eager init for local development (optional). Off by default for production.
if os.environ.get('EAGER_OCR', '').lower() in ('1', 'true', 'yes'):
    init_paddle_ocr()
else:
    print("[SYSTEM] PaddleOCR initialized lazily (models load on first scan).")




# Helper functions
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'jfif', 'jpe'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_confirmation_email(user_email, confirm_url):
    """Envoie un email de confirmation via SMTP"""
    sender_email = os.environ.get('MAIL_USERNAME')
    sender_password = os.environ.get('MAIL_PASSWORD')
    smtp_server = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('MAIL_PORT', 587))

    if not sender_email or not sender_password:
        print("[WARNING] Credentials MAIL_USERNAME/MAIL_PASSWORD non configurés. Email sauté.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Confirmez votre adresse email - FactuScan"
    msg["From"] = f"FactuScan <{sender_email}>"
    msg["To"] = user_email

    html = f"""
    <div style="font-family: 'Inter', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1e1e2e;">
        <h2 style="color: #6366f1;">Bienvenue sur FactuScan !</h2>
        <p>Merci de vous être inscrit. Pour activer votre compte et commencer à gérer vos factures en Tunisie, veuillez confirmer votre adresse email :</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{confirm_url}" style="background: #6366f1; color: white; padding: 12px 25px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">Confirmer mon compte</a>
        </div>
        <p style="font-size: 0.8rem; color: #777;">Si le lien ne fonctionne pas, copiez ceci : <br>{confirm_url}</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, user_email, msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError as e:
        if '5.7.9' in str(e):
            print("[MAIL ERROR] CONFIGURATION REQUISE : Vous utilisez un ID Client au lieu d'un 'Mot de passe d'application'. Générez-en un ici : https://myaccount.google.com/apppasswords")
        else:
            print(f"[MAIL ERROR] Échec de l'authentification : {e}")
        return False
    except Exception as e:
        print(f"[MAIL ERROR] {e}")
        return False

def send_welcome_email(user_email, username):
    """Envoie un email de bienvenue après activation du compte"""
    sender_email = os.environ.get('MAIL_USERNAME')
    sender_password = os.environ.get('MAIL_PASSWORD')
    smtp_server = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('MAIL_PORT', 587))

    if not sender_email or not sender_password:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Inscription réussie - Bienvenue sur FactuScan"
    msg["From"] = f"FactuScan <{sender_email}>"
    msg["To"] = user_email

    html = f"""
    <div style="font-family: 'Inter', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1e1e2e; border: 1px solid #eee; border-radius: 12px;">
        <h2 style="color: #6366f1; text-align: center;">Inscription confirmée !</h2>
        <p>Bonjour <strong>{username}</strong>,</p>
        <p>Nous avons le plaisir de vous informer que votre compte <strong>FactuScan</strong> a été activé avec succès.</p>
        <p>Vous pouvez désormais vous connecter et profiter de toute la puissance de notre IA pour la gestion de vos factures tunisiennes.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{url_for('login', _external=True)}" style="background: #6366f1; color: white; padding: 12px 25px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">Accéder à mon espace</a>
        </div>
        <p style="color: #777; font-size: 0.9rem;">Si vous avez des questions, n'hésitez pas à répondre à cet e-mail.</p>
        <p>L'équipe FactuScan</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, user_email, msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError as e:
        if '5.7.9' in str(e):
            print("[WELCOME MAIL ERROR] Gmail nécessite un 'Mot de passe d'application'.")
        else:
            print(f"[WELCOME MAIL ERROR] Échec d'authentification : {e}")
        return False
    except Exception as e:
        print(f"[WELCOME MAIL ERROR] {e}")
        return False

def extract_with_gemini_multimodal(filepath, mime_type):
    """Send image/PDF directly to Gemini to extract data using vision-language capabilities"""
    if not GOOGLE_API_KEY:
        return None, None
    
    try:
        # Open file as binary
        with open(filepath, "rb") as f:
            file_data = f.read()
            
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Prepare content parts
        prompt = """Act as a Tunisian accounting expert. Analyze the attached invoice image carefully.
        Extract the following fields and return ONLY a valid JSON object:
        {
          "invoice_number": "number or dash if missing",
          "invoice_date": "DD/MM/YYYY",
          "supplier": "Company Name",
          "ice": "15-digit number",
          "ht_amount": float,
          "vat_amount": float,
          "total_amount": float,
          "raw_text": "A full precise transcription of all visible text"
        }
        Be accurate with amounts. If a number has a comma, use a dot. Return null for fields you cannot find with high confidence."""
        
        content = [
            prompt,
            {
                "mime_type": mime_type,
                "data": file_data
            }
        ]
        
        response = model.generate_content(content)
        
        # Robust response checking
        if not response or not response.candidates:
             print("[GEMINI ERROR] No candidates.")
             return None, None
        
        if response.prompt_feedback and response.prompt_feedback.block_reason:
             print(f"[GEMINI BLOCKED] Reason: {response.prompt_feedback.block_reason}")
             
        t = response.text.strip()
        print(f"[GEMINI RAW] {t[:100]}...") # Log start of response
        
        # Improved JSON Extraction from likely markdown blocks
        clean_json = t.replace('```json', '').replace('```', '').strip()
        if "{" in clean_json and "}" in clean_json:
            try:
                start = clean_json.find("{")
                end = clean_json.rfind("}") + 1
                data = json.loads(clean_json[start:end])
                
                # Format cleaning
                for field in ['ht_amount', 'vat_amount', 'total_amount']:
                    val = data.get(field)
                    if isinstance(val, str):
                        try:
                            data[field] = float(val.replace(' ', '').replace(',', '.'))
                        except:
                            data[field] = None
                
                return data, data.get('raw_text', "Données extraites par Gemini AI.")
            except Exception as e:
                print(f"[GEMINI JSON ERROR] {e}")
                
        return None, None
    except google.api_core.exceptions.ResourceExhausted:
        print("[GEMINI QUOTA] Quota épuisé (429). Passage au mode secours OCR local...")
        return None, None
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"[CRITICAL GEMINI ERROR]\n{error_msg}")
        return None, None

import requests # Ajouté pour OCR.Space et Z.IA

def extract_with_zai(filepath):
    """Extraction avec Z.IA (BigModel GLM-OCR) - Très précis"""
    zai_key = os.environ.get('Z_AI_API_KEY')
    if not zai_key:
        return None
    
    try:
        print("[Z.IA] Tentative d'extraction...")
        headers = {"Authorization": f"Bearer {zai_key}"}
        
        # 1. Upload
        with open(filepath, "rb") as f:
            files = {'file': (os.path.basename(filepath), f, 'application/octet-stream')}
            r_up = requests.post("https://open.bigmodel.cn/api/paas/v4/files", 
                               headers=headers, files=files, data={'purpose': 'agent'}, timeout=30)
        
        if r_up.status_code != 200: return None
        file_id = r_up.json().get("id")
        
        # 2. Parse
        payload = {"model": "glm-ocr", "file": file_id}
        response = requests.post("https://open.bigmodel.cn/api/paas/v4/layout_parsing", 
                               headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            return response.json().get("content", "")
    except Exception as e:
        print(f"[Z.IA ERROR] {e}")
    return None

def extract_text_with_ocr_space(filepath):
    """Extract text using OCR.Space API (Powerful Free Cloud OCR)"""
    ocr_key = os.environ.get('OCR_SPACE_API_KEY')
    if not ocr_key:
        return None
    
    try:
        print(f"[OCR.SPACE] Traitement de {filepath}...")
        payload = {
            'apikey': ocr_key,
            'language': 'fre',
            'isOverlayRequired': False,
            'FileType': 'Auto',
            'isTable': True,
            'OCREngine': '2',
        }
        
        with open(filepath, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image',
                            files={'filename': f},
                            data=payload,
                            timeout=60)
            
        result = r.json()
        if result.get('OCRExitCode') == 1:
            parsed_results = result.get('ParsedResults', [])
            if parsed_results:
                return parsed_results[0].get('ParsedText', '')
        
        # Log why OCR.Space failed
        exit_code = result.get('OCRExitCode', 'N/A')
        err_msg = result.get('ErrorMessage', 'N/A')
        err_details = result.get('ErrorDetails', 'N/A')
        print(f"[OCR.SPACE API ERROR] ExitCode={exit_code}, ErrorMessage={err_msg}, ErrorDetails={err_details}")
        
        return None
    except Exception as e:
        print(f"[OCR.SPACE ERROR] {e}")
        return None

def parse_ocr_text_for_invoice_fields(text):
    """Extract invoice data from OCR text using regex patterns (Tunisian + US invoice fallback)."""
    data = {
        'invoice_number': None,
        'invoice_date': None,
        'supplier': None,
        'ice': None,
        'billing_address': None,
        'due_date': None,
        'invoice_status': None,
        'currency': None,
        'ht_amount': None,
        'vat_amount': None,
        'vat_rate': None,
        'total_amount': None,
        'line_items': []
    }

    lines = [line.strip() for line in re.split(r'[\r\n]+', text) if line.strip()]
    upper_text = text.upper()

    # 1. ICE Detection (15 digits)
    ice_match = re.search(r'ICE\s*[:#]?\s*([0-9]{15})', text, re.IGNORECASE)
    if not ice_match:
        ice_match = re.search(r'([0-9]{15})', text)
    if ice_match:
        data['ice'] = ice_match.group(1)

    # 2. Invoice number patterns
    invoice_num_patterns = [
        r'INVOICE\s*#\s*[:]?\s*([A-Za-z0-9-]+)',
        r'INVOICE\s*NUMBER\s*[:#]?\s*([A-Za-z0-9-]+)',
        r'INVOICE\s*[:#]?\s*([A-Za-z0-9-]+)',
        r'N[o°]\s*[:#]?\s*([A-Za-z0-9-]+)',
        r'FACTURE\s*[:#-]?\s*([A-Za-z0-9-]+)',
        r'N[°°]?\s*FACTURE\s*[:#]?\s*([A-Za-z0-9-]+)'
    ]
    for pattern in invoice_num_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = match.group(1).strip()
            if 2 < len(val) < 40:
                data['invoice_number'] = val
                break

    if not data['invoice_number']:
        for idx, line in enumerate(lines):
            if re.search(r'INVOICE\s*#|INVOICE\s*NUMBER|FACTURE|N[o°]', line, re.IGNORECASE):
                if idx + 1 < len(lines):
                    candidate = lines[idx + 1].strip()
                    if re.search(r'[A-Za-z0-9-]{3,}', candidate):
                        data['invoice_number'] = candidate
                        break

    if not data['invoice_number']:
        data['invoice_number'] = '_'

    # 3. Invoice date patterns
    date_patterns = [
        r'INVOICE\s*DATE\s*[:#]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})',
        r'DATE\s*[:#]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})',
        r'([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})'
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            found_date = match.group(1).strip()
            if len(found_date) >= 8:
                data['invoice_date'] = found_date
                break

    # 4. Supplier detection
    if "REDAL" in upper_text:
        data['supplier'] = "REDAL"
    elif "LYDEC" in upper_text:
        data['supplier'] = "LYDEC"
    elif "IAM" in upper_text or "TELECOM" in upper_text:
        data['supplier'] = "MAROC TELECOM"
    elif "MAROC" in upper_text and "TELECOM" in upper_text:
        data['supplier'] = "MAROC TELECOM"
    else:
        supplier_patterns = [
            r'FOURNISSEUR\s*[:#]?\s*([A-Za-z.\s]{3,})',
            r'SOCI[ÉE]T[ÉE]\s*([A-Za-z.\s]{3,})',
            r'PLEASE\s+MAKE\s+CHECKS\s+PAYABLE\s+TO\s*[:]?\s*([A-Za-z.\s]+)'
        ]
        for pattern in supplier_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name) > 3:
                    data['supplier'] = name
                    break

        if not data['supplier'] and lines:
            first_line = lines[0]
            if not re.search(r'INVOICE|FACTURE|BILL TO|SHIP TO|DUE DATE|TERMS|QTY|DESCRIPTION|AMOUNT', first_line, re.IGNORECASE):
                data['supplier'] = first_line

    # 5. Amount/Total extraction
    data['billing_address'] = extract_billing_address(lines)

    due_patterns = [
        r'DUE DATE\s*[:#]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})',
        r'PAYMENT DUE\s*[:#]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})',
        r'DATE\s+D[EÉ]CH[EÈ]ANCE\s*[:#]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})'
    ]
    for pattern in due_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['due_date'] = match.group(1).strip()
            break

    if re.search(r'\bPAID\b|\bPAY[EÉ]\b', upper_text) and not re.search(r'\bPAYMENT DUE\b|\bDUE\b|\bUNPAID\b', upper_text):
        data['invoice_status'] = 'PAID'
    elif re.search(r'\bUNPAID\b|\bDUE\b|\bPAYMENT DUE\b|\bSOLDE D[UÛ]\b', upper_text):
        data['invoice_status'] = 'DUE'

    if '€' in text or 'EUR' in upper_text:
        data['currency'] = 'EUR'
    elif '\$' in text or 'USD' in upper_text:
        data['currency'] = 'USD'
    elif re.search(r'\b(TND|DT|MAD|DHS|DH)\b', upper_text):
        data['currency'] = 'TND'

    total_patterns = [
        r'INVOICE\s*TOTAL\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'TOTAL\s*A\s*PAYER\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'SOMME\s+A\s*PAYER\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'TOTAL\s*TTC\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'NET\s*A\s*PAYER\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'TOTAL\s*[:#]?\s*\$?\s*([0-9.,\s]{1,15})'
    ]
    for p in total_patterns:
        matches = list(re.finditer(p, text, re.IGNORECASE))
        if matches:
            match = matches[-1]
            val_str = match.group(1).strip()
            num_match = re.search(r'([0-9][0-9.,\s]+)$', val_str)
            if not num_match:
                num_match = re.search(r'([0-9][0-9.,\s]+)', val_str)
            if num_match:
                val = clean_amount(num_match.group(1))
                if val and 1 < val < 100000:
                    data['total_amount'] = val
                    break

    ht_patterns = [
        r'SUBTOTAL\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'SOMME\s+HORS\s+TAXES\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'TOTAL\s*HT\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'HT\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'SOUS[-\s]*TOTAL\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'MONTANT\s*HT\s*[:#]?\s*\$?\s*([0-9.,\s]+)'
    ]
    for p in ht_patterns:
        matches = list(re.finditer(p, text, re.IGNORECASE))
        if matches:
            match = matches[-1]
            val = clean_amount(match.group(1))
            if val and val < 100000:
                data['ht_amount'] = val
                break

    if not data.get('total_amount'):
        total_candidates = re.findall(r'\$?\s*([0-9]{1,3}(?:[0-9.,]*[0-9])?)', text)
        amounts = [clean_amount(n) for n in total_candidates if n]
        valid_amounts = [a for a in amounts if a and a > 10]
        if valid_amounts:
            data['total_amount'] = max(valid_amounts)

    vat_patterns = [
        r'MONTANT\s+TVA\s*[:#]?\s*\$?\s*([0-9.,\s]+)',
        r'TVA\s*[:#]?\s*\$?\s*([0-9.,\s]+)(?!%)',
        r'SALES\s+TAX\s*[0-9]{1,2}%\s*[:#]?\s*\$?\s*([0-9.,\s]+)'
    ]
    for p in vat_patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            val = clean_amount(match.group(1))
            if val and (not data.get('total_amount') or val < data['total_amount']):
                data['vat_amount'] = val
                break

    vat_rate_pattern = re.search(r'([0-9]{1,2}(?:\.[0-9]+)?)\s*%', text)
    if vat_rate_pattern:
        try:
            data['vat_rate'] = float(vat_rate_pattern.group(1))
        except ValueError:
            data['vat_rate'] = None

    if data.get('total_amount') and not data.get('ht_amount') and data.get('vat_rate') is not None:
        data['ht_amount'] = round(data['total_amount'] / (1 + data['vat_rate'] / 100), 2)
        data['vat_amount'] = round(data['total_amount'] - data['ht_amount'], 2)
    elif data.get('ht_amount') and data.get('vat_rate') is not None and not data.get('vat_amount'):
        data['vat_amount'] = round(data['ht_amount'] * (data['vat_rate'] / 100), 2)
        data['total_amount'] = round(data['ht_amount'] + data['vat_amount'], 2)

    if data.get('total_amount') and data.get('ht_amount') and not data.get('vat_amount'):
        data['vat_amount'] = round(data['total_amount'] - data['ht_amount'], 2)
    elif data.get('total_amount') and data.get('vat_amount') and not data.get('ht_amount'):
        data['ht_amount'] = round(data['total_amount'] - data['vat_amount'], 2)

    data['line_items'] = extract_line_items(lines)
    return data


def clean_amount(value):
    if value is None:
        return None
    text = re.sub(r'[^0-9.,]', '', str(value)).replace(',', '.')
    if text.count('.') > 1:
        last_dot = text.rfind('.')
        text = text[:last_dot].replace('.', '') + text[last_dot:]
    try:
        return float(text)
    except ValueError:
        return None


def parse_number(value):
    if value is None:
        return None
    match = re.search(r'(\d+(?:[.,]\d+)?)', str(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', '.'))
    except ValueError:
        return None


def extract_line_items(lines):
    items = []
    header_index = None
    for idx, line in enumerate(lines):
        if re.search(r'\bDESCRIPTION\b', line, re.IGNORECASE) and re.search(r'\bQTY\b|\bQUANTITY\b|\bQTE\b', line, re.IGNORECASE):
            header_index = idx
            break

    if header_index is not None:
        for row in lines[header_index + 1:]:
            if not row.strip() or re.search(r'\bTOTAL\b|\bSUBTOTAL\b|\bVAT\b|\bTVA\b|\bMONTANT\b', row, re.IGNORECASE):
                continue
            parts = re.split(r'\s{2,}', row)
            if len(parts) < 2:
                continue
            description = ' '.join(parts[:-3]) if len(parts) >= 4 else parts[0]
            quantity = parse_number(parts[-3]) if len(parts) >= 4 else None
            unit_price = clean_amount(parts[-2]) if len(parts) >= 3 else None
            total_price = clean_amount(parts[-1])
            if total_price is not None and description.strip():
                items.append({
                    'description': description.strip(),
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price
                })

    if not items:
        for row in lines:
            parts = re.split(r'\s{2,}', row)
            if len(parts) < 3:
                continue
            total_price = clean_amount(parts[-1])
            unit_price = clean_amount(parts[-2])
            quantity = parse_number(parts[-3])
            description = ' '.join(parts[:-3]) if len(parts) >= 4 else parts[0]
            if total_price is not None and description.strip():
                items.append({
                    'description': description.strip(),
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price
                })
            if len(items) >= 8:
                break

    return items


def extract_billing_address(lines):
    for idx, line in enumerate(lines):
        if re.search(r'\bBILL TO\b|\bBILLING ADDRESS\b|\bADRESSE DE FACTURATION\b', line, re.IGNORECASE):
            address_parts = []
            for next_line in lines[idx + 1:idx + 6]:
                if not next_line.strip() or re.search(r'\bINVOICE\b|\bDATE\b|\bTOTAL\b|\bQTY\b|\bDESCRIPTION\b|\bAMOUNT\b|\bTVA\b|\bTAX\b', next_line, re.IGNORECASE):
                    break
                address_parts.append(next_line.strip())
            if address_parts:
                return ', '.join(address_parts)
    return None


def process_with_paddleocr(filepath, file_type):
    all_extracted_text_lines = []
    full_raw_text = ""
    html_blocks = []
    error_messages = []

    # Ensure PaddleOCR models are loaded lazily on first scan (memory-safe)
    init_paddle_ocr()

    def process_paddle_structure(image_path):
        nonlocal all_extracted_text_lines, full_raw_text, html_blocks
        paddle_result = pp_structure_analyzer(image_path, return_ocr_result_in_table=True)
        if not paddle_result:
            return
        for region in paddle_result:
            if region.get('type') == 'table' and isinstance(region.get('res'), dict):
                html = region['res'].get('html')
                if html:
                    html_blocks.append(html)
                table_text = region['res'].get('text') or region['res'].get('table_text')
                if table_text:
                    all_extracted_text_lines.extend([line.strip() for line in table_text if line and line.strip()])
                    full_raw_text += "\n".join([line.strip() for line in table_text if line and line.strip()]) + "\n"

            res = region.get('res', [])
            lines = res[0] if isinstance(res, tuple) else res
            if isinstance(lines, list):
                for line in lines:
                    if isinstance(line, dict) and line.get('text'):
                        text = line['text'].strip()
                        if text:
                            all_extracted_text_lines.append(text)
                            full_raw_text += text + "\n"
                    elif isinstance(line, (list, tuple)) and len(line) >= 2 and isinstance(line[1], (list, tuple)):
                        text = line[1][0] if line[1] and isinstance(line[1], (list, tuple)) else None
                        if text:
                            all_extracted_text_lines.append(text.strip())
                            full_raw_text += text.strip() + "\n"

    if pp_structure_analyzer:
        try:
            if file_type == "application/pdf":
                images = pdf2image.convert_from_path(filepath)
                for image in images:
                    temp_image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_paddle_page_{uuid.uuid4().hex}.png")
                    image.save(temp_image_path)
                    process_paddle_structure(temp_image_path)
                    os.remove(temp_image_path)
            else:
                process_paddle_structure(filepath)

            if full_raw_text.strip():
                return all_extracted_text_lines, full_raw_text.strip(), "\n".join(html_blocks), None
        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            print(f"[PaddleOCR Structure ERROR]\n{error_msg}")
            error_messages.append(f"PaddleOCR Structure failed: {str(e)}")

    if paddle_ocr_reader:
        try:
            def ocr_image(image_path):
                nonlocal all_extracted_text_lines, full_raw_text
                ocr_result = paddle_ocr_reader.ocr(image_path)
                if ocr_result and isinstance(ocr_result, list):
                    pages = ocr_result
                    if pages and isinstance(pages[0], list):
                        for line in pages[0]:
                            if len(line) >= 2 and isinstance(line[1], (list, tuple)):
                                text = line[1][0]
                            elif len(line) >= 2 and isinstance(line[1], str):
                                text = line[1]
                            else:
                                text = None
                            if text:
                                text = text.strip()
                                if text:
                                    all_extracted_text_lines.append(text)
                                    full_raw_text += text + "\n"

            if file_type == "application/pdf":
                images = pdf2image.convert_from_path(filepath)
                for image in images:
                    temp_image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_paddle_page_{uuid.uuid4().hex}.png")
                    image.save(temp_image_path)
                    ocr_image(temp_image_path)
                    os.remove(temp_image_path)
            else:
                ocr_image(filepath)

            if full_raw_text.strip():
                return all_extracted_text_lines, full_raw_text.strip(), "", None
        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            print(f"[PaddleOCR fallback ERROR]\n{error_msg}")
            error_messages.append(f"PaddleOCR fallback failed: {str(e)}")

    final_error = " | ".join(error_messages) if error_messages else "PaddleOCR structure analyzer not initialized."
    return None, None, None, final_error


def map_extracted_data_to_response_format(extracted_data, raw_text_lines):
    return {
        "text": raw_text_lines,
        "structured": {
            "invoice_number": extracted_data.get('invoice_number'),
            "invoice_date": extracted_data.get('invoice_date'),
            "supplier": extracted_data.get('supplier'),
            "ice": extracted_data.get('ice'),
            "billing_address": extracted_data.get('billing_address'),
            "due_date": extracted_data.get('due_date'),
            "currency": extracted_data.get('currency'),
            "invoice_status": extracted_data.get('invoice_status'),
            "ht_amount": extracted_data.get('ht_amount'),
            "vat_amount": extracted_data.get('vat_amount'),
            "vat_rate": extracted_data.get('vat_rate'),
            "total_amount": extracted_data.get('total_amount'),
            "line_items": extracted_data.get('line_items') or []
        }
    }

def validate_data(data):
    """Validate ICE and check the sum: HT + TVA = Total"""
    validations = {
        'ice_valid': True,
        'math_valid': True,
        'errors': []
    }
    
    # 1. Check ICE (15 digits)
    if data.get('ice'):
        # Remove spaces/dots
        ice_clean = re.sub(r'[\s\.]', '', str(data['ice']))
        if not re.match(r'^\d{15}$', ice_clean):
            validations['ice_valid'] = False
            validations['errors'].append("L'ICE doit comporter exactement 15 chiffres.")
    else:
        validations['ice_valid'] = False
        validations['errors'].append("ICE introuvable ou illisible.")
    
    # 2. Check math: HT + VAT ~= Total (with a small margin for rounding)
    ht = data.get('ht_amount') or 0
    vat = data.get('vat_amount') or 0
    total = data.get('total_amount') or 0
    
    if total > 0:
        calculated_total = ht + vat
        if abs(calculated_total - total) > 0.05: # Allow 0.05 TND margin
            validations['math_valid'] = False
            validations['errors'].append(f"Erreur de calcul: HT ({ht}) + TVA ({vat}) = {calculated_total:.2f} (diffère de {total:.2f})")
    else:
        validations['math_valid'] = False
        validations['errors'].append("Montants (HT/TVA/TTC) introuvables ou illisibles.")
            
    return validations

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/scanner')
def scanner():
    return render_template('scanner.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/docs')
def docs():
    return render_template('docs.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Handle both JSON (AJAX) and form-data submissions
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')

        db = get_db()
        if not db:
            msg = "Base de données indisponible."
            if request.is_json:
                return jsonify({"error": msg}), 503
            flash(msg, "danger")
            return render_template('login.html')

        user = db.query(User).filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            if user.is_authorized:
                user.last_login = datetime.now()
                db.commit()
                login_user(user)
                # Redirect based on role
                redirect_url = url_for('admin_dashboard') if user.role.lower() == 'admin' else url_for('dashboard')
                if request.is_json:
                    return jsonify({"message": "Connexion réussie !", "redirect": redirect_url}), 200
                flash("Connexion réussie !", "success")
                return redirect(redirect_url)
            else:
                msg = "Compte en attente d'autorisation."
                if request.is_json:
                    return jsonify({"error": msg}), 403
                flash(msg, "warning")
        else:
            msg = "Nom d'utilisateur ou mot de passe incorrect."
            if request.is_json:
                return jsonify({"error": msg}), 401
            flash(msg, "danger")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        
        # Extract fields
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')
        full_name = data.get('full_name')
        company_name = data.get('company_name')
        city = data.get('city')
        country = data.get('country')
        purpose_of_use = data.get('purpose_of_use')
        additional_info = data.get('additional_info')
        subscription_type = data.get('subscription_type', 'Basic')

        db = get_db()
        if not db:
            return jsonify({"error": "Base de données indisponible."}), 503 if request.is_json else (flash("DB Error", "danger") or render_template('register.html'))

        # 1. Validation: Required fields & Format
        required_fields = [username, email, password, full_name, city, country, purpose_of_use]
        if not all(required_fields):
            msg = "Veuillez remplir tous les champs obligatoires."
            return jsonify({"error": msg}), 400 if request.is_json else (flash(msg, "warning") or render_template('register.html'))

        # Email format validation
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            return jsonify({"error": "Format d'email invalide."}), 400 if request.is_json else (flash("Email invalide", "danger") or render_template('register.html'))

        # Validation de la localisation
        if not country or len(country) < 2 or not city or len(city) < 2:
            return jsonify({"error": "Veuillez renseigner votre pays et votre ville."}), 400 if request.is_json else (flash("Localisation invalide", "danger") or render_template('register.html'))

        # 2. Validation: Password match
        if password != confirm_password:
            msg = "Les mots de passe ne correspondent pas."
            return jsonify({"error": msg}), 400 if request.is_json else (flash(msg, "danger") or render_template('register.html'))

        # 3. Validation: Password strength (min 8 chars, 1 uppercase, 1 digit)
        if len(password) < 8 or not any(c.isdigit() for c in password) or not any(c.isupper() for c in password):
            msg = "Le mot de passe doit contenir au moins 8 caractères, une majuscule et un chiffre."
            return jsonify({"error": msg}), 400 if request.is_json else (flash(msg, "danger") or render_template('register.html'))

        # 4. Check uniqueness
        existing_user = db.query(User).filter_by(username=username).first()
        if existing_user:
            return jsonify({"error": "Ce nom d'utilisateur existe déjà."}), 409 if request.is_json else (flash("Username taken", "danger") or render_template('register.html'))

        existing_email = db.query(User).filter_by(email=email).first()
        if existing_email:
            return jsonify({"error": "Cet email est déjà utilisé."}), 409 if request.is_json else (flash("Email taken", "danger") or render_template('register.html'))

        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role='user',
            subscription_type=subscription_type,
            full_name=full_name,
            company_name=company_name,
            city=city,
            country=country,
            purpose_of_use=purpose_of_use,
            additional_info=additional_info,
            is_authorized=False
        )
        
        db.add(new_user)
        db.commit()
        
        # Logique de confirmation d'email
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        token = s.dumps(email, salt='email-confirm')
        confirm_url = url_for('confirm_email', token=token, _external=True)
        
        send_confirmation_email(email, confirm_url)

        return jsonify({"message": "Inscription réussie ! Veuillez confirmer votre email."}), 200 if request.is_json else (flash("Vérifiez vos emails pour activer votre compte.", "success") or redirect(url_for('login')))

    return render_template('register.html')

@app.route('/login/google')
def login_google():
    """Redirection vers Google pour l'authentification"""
    redirect_uri = url_for('authorize_google', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/login/google/authorize')
def authorize_google():
    """Gestion du retour de Google"""
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            flash("Échec de la récupération des données Google.", "danger")
            return redirect(url_for('login'))
        
        email = user_info['email']
        full_name = user_info.get('name', email.split('@')[0])
        
        db = get_db()
        user = db.query(User).filter_by(email=email).first()
        
        if not user:
            # Création automatique pour une première connexion Google
            username = email.split('@')[0]
            # Vérification unicité username
            base_username = username
            count = 1
            while db.query(User).filter_by(username=username).first():
                username = f"{base_username}{count}"
                count += 1
            
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(os.urandom(24).hex()), # Mot de passe aléatoire
                full_name=full_name,
                is_authorized=True, # Email déjà vérifié par Google
                email_confirmed=True,
                country='Tunisia', # Par défaut
                city='Tunis'
            )
            db.add(user)
            db.commit()
            send_welcome_email(user.email, user.username)
            
        # Si l'utilisateur existait déjà mais n'était pas autorisé, Google valide son identité
        if not user.is_authorized:
            user.is_authorized = True
            user.email_confirmed = True
            db.commit()

        # Connexion de l'utilisateur
        login_user(user)
        user.last_login = datetime.now()
        db.commit()

        flash(f"Heureux de vous revoir, {user.full_name} !", "success")
        return redirect(url_for('dashboard'))
    except Exception as e:
        error_type = type(e).__name__
        print(f"[OAUTH ERROR] {error_type}: {e}")
        if error_type == 'MismatchingStateError':
            # Message pédagogique pour l'utilisateur
            flash("Erreur de session. Veuillez vous assurer d'utiliser 'http://localhost:5000' dans votre navigateur et non l'adresse IP.", "danger")
        else:
            flash("Erreur lors de la connexion avec Google.", "danger")
        return redirect(url_for('login'))

@app.route('/confirm_email/<token>')
def confirm_email(token):
    """Gère le clic sur le lien de confirmation envoyé par mail"""
    try:
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        email = s.loads(token, salt='email-confirm', max_age=3600) # Expire après 1h
    except (SignatureExpired, BadTimeSignature):
        flash("Le lien est invalide ou a expiré.", "danger")
        return redirect(url_for('login'))

    db = get_db()
    user = db.query(User).filter_by(email=email).first()
    if not user:
        flash("Utilisateur introuvable.", "danger")
        return redirect(url_for('login'))

    if user.email_confirmed:
        flash("Email déjà confirmé.", "info")
    else:
        user.email_confirmed = True
        user.is_authorized = True # Activation du compte
        db.commit()
        send_welcome_email(user.email, user.username)
        flash("Votre email a été confirmé ! Vous pouvez maintenant vous connecter.", "success")
    
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db = get_db()
    if request.method == 'POST':
        # Update personal info
        current_user.full_name = request.form.get('full_name', current_user.full_name)
        current_user.company_name = request.form.get('company_name', current_user.company_name)
        current_user.city = request.form.get('city', current_user.city)
        current_user.country = request.form.get('country', current_user.country)
        current_user.purpose_of_use = request.form.get('purpose_of_use', current_user.purpose_of_use)
        current_user.additional_info = request.form.get('additional_info', current_user.additional_info)
        db.commit()
        flash("Profil mis à jour avec succès.", "success")
        return redirect(url_for('profile'))

    # Get activity data
    last_invoice = db.query(Invoice).filter_by(user_id=current_user.id).order_by(Invoice.created_at.desc()).first()
    messages = db.query(Message).filter_by(user_id=current_user.id).order_by(Message.timestamp.desc()).all()
    
    return render_template('profile.html', last_invoice=last_invoice, messages=messages)

@app.route('/profile/upload-image', methods=['POST'])
@login_required
def upload_profile_image():
    if 'profile_image' not in request.files:
        return jsonify({"error": "Aucun fichier"}), 400
    
    file = request.files['profile_image']
    if file and allowed_file(file.filename):
        filename = f"user_{current_user.id}_{uuid.uuid4().hex[:8]}.{file.filename.rsplit('.', 1)[1].lower()}"
        filepath = os.path.join(app.config['PROFILE_FOLDER'], filename)
        file.save(filepath)
        
        db = get_db()
        current_user.profile_image = filename
        db.commit()
        return jsonify({"message": "Image mise à jour", "filename": filename}), 200
    return jsonify({"error": "Format non autorisé"}), 400

@app.route('/profile/send-message', methods=['POST'])
@login_required
def send_message():
    data = request.get_json()
    subject = data.get('subject')
    body = data.get('body')
    
    if not subject or not body:
        return jsonify({"error": "Sujet et message requis"}), 400
        
    db = get_db()
    new_msg = Message(user_id=current_user.id, subject=subject, body=body)
    db.add(new_msg)
    db.commit()
    return jsonify({"message": "Message envoyé à l'administrateur."}), 200

@app.route('/reclamation', methods=['GET', 'POST'])
@login_required
def reclamation():
    if request.method == 'POST':
        subject = request.form.get('subject')
        body = request.form.get('body')
        
        if not subject or not body:
            flash("Veuillez remplir tous les champs.", "warning")
            return render_template('reclamation.html')
            
        db = get_db()
        new_msg = Message(
            user_id=current_user.id,
            subject=subject,
            body=body,
            status='new'
        )
        db.add(new_msg)
        db.commit()
        
        # Emit real-time notification to admin
        socketio.emit('new_reclamation', {
            'user': current_user.username,
            'subject': subject
        })
        
        flash("Votre réclamation a été envoyée avec succès.", "success")
        return redirect(url_for('reclamation'))
    return render_template('reclamation.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for('index'))

@app.route('/packs')
def packs():
    db = get_db()
    packs_list = []
    if db:
        db_packs = db.query(Pack).all()
        for p in db_packs:
            packs_list.append({
                'name': p.name,
                'description': p.description,
                'price_eur': int(p.price_eur) if p.price_eur.is_integer() else p.price_eur,
                'price_tnd': int(p.price_tnd) if p.price_tnd.is_integer() else p.price_tnd,
                'limit_text': p.limit_text,
                'features': json.loads(p.features_json) if p.features_json else [],
                'is_featured': p.is_featured
            })
    return render_template('packs.html', packs=packs_list)

@app.route('/upload', methods=['POST'])
@app.route('/api/upload', methods=['POST'])
@app.route('/scan', methods=['POST']) # New route for PaddleOCR integration
def upload_file():
    try:
        # Debug logging
        print(f"[UPLOAD] Request files: {request.files}")
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        
        if file and allowed_file(file.filename):
            # Generate unique filename
            filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Detect file type and normalize
            # Use file extension instead of python-magic (not available on Windows)
            ext = filename.rsplit('.', 1)[1].lower()
            if ext in ['jpg', 'jpeg', 'jfif', 'jpe']:
                file_type = "image/jpeg"
            elif ext == 'png':
                file_type = "image/png"
            elif ext == 'pdf':
                file_type = "application/pdf"
            else:
                file_type = "image/jpeg"
                
            # Initialize variables for extracted data
            extracted_text_lines = []
            full_raw_text = ""
            structured_invoice_data = {}
            html_content = ""
            gemini_multimodal_used = False
            
            # --- OCR Pipeline ---
            # 1. Try Gemini Multimodal First (Best & Lightest)
            gemini_data, gemini_text = extract_with_gemini_multimodal(filepath, file_type)
            
            if gemini_data:
                full_raw_text = gemini_text or "[Données extraites directement par Gemini AI]"
                extracted_text_lines = full_raw_text.split('\n')
                structured_invoice_data = gemini_data
                gemini_multimodal_used = True
                print("[OCR] Gemini Multimodal used.")
            # 2. If Gemini Multimodal was not used or failed, proceed with PaddleOCR PP-StructureV3
            if not gemini_multimodal_used:
                print("[OCR] Processing with PaddleOCR PP-StructureV3...")
                paddle_text_lines, paddle_raw_text, paddle_html, paddle_error = process_with_paddleocr(filepath, file_type)
                
                if paddle_raw_text:
                    full_raw_text = paddle_raw_text
                    extracted_text_lines = paddle_text_lines
                    html_content = paddle_html or ""
                    # Use regex to extract structured data from PaddleOCR's raw text
                    structured_invoice_data = parse_ocr_text_for_invoice_fields(full_raw_text)
                    print("[OCR] PaddleOCR PP-StructureV3 used.")
                else:
                    print(f"[OCR] PaddleOCR failed: {paddle_error}")
                    # --- Fallback to OCR.Space ---
                    print("[OCR] Trying OCR.Space fallback...")
                    ocr_space_text = extract_text_with_ocr_space(filepath)
                    if ocr_space_text:
                        full_raw_text = ocr_space_text
                        extracted_text_lines = full_raw_text.split('\n')
                        structured_invoice_data = parse_ocr_text_for_invoice_fields(full_raw_text)
                        print("[OCR] OCR.Space fallback used.")
                    else:
                        # If all OCR methods failed, clean up and return error
                        os.remove(filepath) 
                        return jsonify({"error": "Échec de l'extraction OCR. Veuillez vérifier le fichier ou les logs."}), 422


            # Refine structured data with Gemini Text Analysis if raw text was obtained from other OCRs
            if full_raw_text and not gemini_data and GOOGLE_API_KEY:
                refine_data = extract_with_gemini(full_raw_text)
                if refine_data:
                    # Merge refined data, prioritizing Gemini's output for specific fields
                    # Only update fields if Gemini provides a non-None value
                    for key in ['invoice_number', 'invoice_date', 'supplier', 'ice', 'ht_amount', 'vat_amount', 'total_amount']:
                        if refine_data.get(key) is not None and refine_data[key] != structured_invoice_data.get(key):
                            structured_invoice_data[key] = refine_data[key] # Prioritize Gemini's refined value
                    # Also update the detailed fields for DB saving
                    if 'ht_amount' in refine_data: structured_invoice_data['ht_amount'] = refine_data['ht_amount']
                    if 'vat_amount' in refine_data: structured_invoice_data['vat_amount'] = refine_data['vat_amount']
                    print("[OCR] Gemini Text Analysis used for refinement.")

            # Ensure HT estimation if possible (for DB saving)
            if structured_invoice_data.get('total_amount') and structured_invoice_data.get('vat_amount') and not structured_invoice_data.get('ht_amount'):
                structured_invoice_data['ht_amount'] = structured_invoice_data['total_amount'] - structured_invoice_data['vat_amount']

            # Validate the results
            validations = validate_data(structured_invoice_data)
            
            # Save to database
            invoice_id = None
            db = get_db()
            if db:
                try:
                    new_invoice = Invoice(
                        user_id=current_user.id,
                        filename=filename, # Keep original filename
                        invoice_number=structured_invoice_data.get('invoice_number', '_'),
                        invoice_date=structured_invoice_data.get('invoice_date'),
                        supplier=structured_invoice_data.get('supplier'),
                        ice=structured_invoice_data.get('ice'), # ICE is a string
                        ht_amount=structured_invoice_data.get('ht_amount'),
                        vat_amount=structured_invoice_data.get('vat_amount'),
                        total_amount=structured_invoice_data.get('total_amount'),
                        extracted_text=full_raw_text
                    )
                    db.add(new_invoice)
                    db.commit()
                    invoice_id = new_invoice.id
                except Exception as db_e:
                    print(f"[DATABASE ERROR] {db_e}")
                    db.rollback()
            
            # --- GLOBAL SAFETY FILTER (Anti-Fake Amounts) ---
            # Suppression de tout montant absurde avant de répondre pour éviter les faux positifs d'IDs
            for key in ['total_amount', 'ht_amount', 'vat_amount']:
                val = structured_invoice_data.get(key)
                if val and isinstance(val, (int, float)):
                    if val > 100000:
                        print(f"[SECURITY] Blocking absurd amount: {val} for {key}")
                        structured_invoice_data[key] = None
            
            # Double check: Total must be >= HT
            if structured_invoice_data.get('total_amount') and structured_invoice_data.get('ht_amount'):
                if structured_invoice_data['total_amount'] < structured_invoice_data['ht_amount']:
                    structured_invoice_data['total_amount'] = None 

            # Clean up the uploaded file after successful processing
            os.remove(filepath)

            mapped_response = map_extracted_data_to_response_format(structured_invoice_data, extracted_text_lines)
            return jsonify({
                "id": invoice_id,
                "filename": filename,
                "raw": full_raw_text,
                "extracted_text": full_raw_text,
                "text": extracted_text_lines,
                "html": html_content,
                "extracted_data": mapped_response['structured'],
                "structured": mapped_response['structured'],
                "validations": validations,
                "ai_active": GOOGLE_API_KEY is not None,
                "message": "Fichier traité avec succès"
            })
        
        return jsonify({"error": "Type de fichier non autorisé"}), 400
    except Exception as global_e:
        print(f"[GLOBAL UPLOAD ERROR] {global_e}")
        return jsonify({"error": f"Erreur interne: {str(global_e)}"}), 500

@app.route('/invoices', methods=['GET'])
@login_required
def get_invoices():
    db = get_db()
    if not db:
        return jsonify([]), 200
        
    # Start with user-specific invoices by default
    query = db.query(Invoice).filter(Invoice.user_id == current_user.id)
    
    # If the current user is an admin, they can see all invoices
    if current_user.role.lower() == 'admin':
        query = db.query(Invoice)
    
    invoices = query.all()
    result = []
    for invoice in invoices:
        result.append({
            "id": invoice.id,
            "filename": invoice.filename,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "supplier": invoice.supplier,
            "ice": invoice.ice,
            "vat_amount": invoice.vat_amount,
            "total_amount": invoice.total_amount,
            "created_at": invoice.created_at.isoformat()
        })
    return jsonify(result)

@app.route('/invoices/<int:invoice_id>', methods=['GET'])
@login_required
def get_invoice(invoice_id):
    db = get_db()
    if not db:
        return jsonify({"error": "Database unavailable"}), 503
    
    query = db.query(Invoice).filter_by(id=invoice_id)
    if current_user.role.lower() != 'admin':
        query = query.filter_by(user_id=current_user.id)
    invoice = query.first()
    
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404
    
    return jsonify({
        "id": invoice.id,
        "filename": invoice.filename,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "supplier": invoice.supplier,
        "ice": invoice.ice,
        "vat_amount": invoice.vat_amount,
        "total_amount": invoice.total_amount,
        "extracted_text": invoice.extracted_text,
        "created_at": invoice.created_at.isoformat()
    })

@app.route('/invoices/<int:invoice_id>', methods=['PUT'])
@login_required
def update_invoice(invoice_id):
    db = get_db()
    if not db:
        return jsonify({"error": "Database unavailable"}), 503
    
    query = db.query(Invoice).filter_by(id=invoice_id)
    if current_user.role.lower() != 'admin':
        query = query.filter_by(user_id=current_user.id)
    invoice = query.first()
    
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404
    
    data = request.get_json()
    if 'invoice_number' in data:
        invoice.invoice_number = data['invoice_number']
    if 'invoice_date' in data:
        invoice.invoice_date = data['invoice_date']
    if 'supplier' in data:
        invoice.supplier = data['supplier']
    if 'ice' in data:
        invoice.ice = data['ice']
    if 'ht_amount' in data:
        invoice.ht_amount = float(data['ht_amount'])
    if 'vat_amount' in data:
        invoice.vat_amount = float(data['vat_amount'])
    if 'total_amount' in data:
        invoice.total_amount = float(data['total_amount'])
    
    invoice.updated_at = datetime.now()
    db.commit()
    
    return jsonify({
        "message": "Invoice updated successfully",
        "invoice": {
            "id": invoice.id,
            "filename": invoice.filename,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "supplier": invoice.supplier,
            "ice": invoice.ice,
            "ht_amount": invoice.ht_amount,
            "vat_amount": invoice.vat_amount,
            "total_amount": invoice.total_amount,
            "updated_at": invoice.updated_at.isoformat()
        }
    })

@app.route('/invoices/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_invoice(invoice_id):
    db = get_db()
    if not db:
        return jsonify({"error": "Database unavailable"}), 503
    
    query = db.query(Invoice).filter_by(id=invoice_id)
    if current_user.role.lower() != 'admin':
        query = query.filter_by(user_id=current_user.id)
    invoice = query.first()
    
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404
    
    # Delete file from filesystem
    if invoice.filename:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], invoice.filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Error removing file {filepath}: {e}")
    
    # Delete from database
    db.delete(invoice)
    db.commit()
    
    return jsonify({"message": "Invoice deleted successfully"})

@app.route('/voice/command', methods=['POST'])
@login_required
def voice_command():
    """Process voice command manually or with AI"""
    data = request.get_json()
    command = data.get('command', '')
    
    if not command:
        return jsonify({"response": "Je n'ai pas entendu votre commande."})

    try:
        # Pre-process command
        cmd_lower = command.lower()
        
        # 1. Get current stats for context (always attempt)
        total_ttc = 0.0
        invoice_count = 0
        db = get_db()
        if db:
            try:
                invoice_count = db.query(Invoice).filter_by(user_id=current_user.id).count()
                total_ttc = float(db.query(Invoice).filter_by(user_id=current_user.id).with_entities(func.coalesce(func.sum(Invoice.total_amount), 0.0)).scalar() or 0)
            except:
                pass

        # 2. KEYWORD FALLBACK (Works without AI)
        if "total" in cmd_lower or "combien" in cmd_lower or "montant" in cmd_lower:
            return jsonify({"response": f"D'après vos données, le montant total des factures est de {total_ttc:.2f} dinars pour {invoice_count} factures."})
        
        if "résumé" in cmd_lower or "qu'est-ce que j'ai" in cmd_lower or "nombre" in cmd_lower:
            return jsonify({"response": f"Vous avez actuellement {invoice_count} factures enregistrées dans votre tableau de bord FactuScan."})

        if "aide" in cmd_lower or "comment" in cmd_lower or "peux-tu" in cmd_lower:
            return jsonify({"response": "Je peux vous donner le total de vos dépenses, le nombre de vos factures, ou lire à haute voix les résultats d'un scan. Dites 'total' ou 'résumé'."})

        # 3. SMART AI FALLBACK (If keywords don't match)
        if GOOGLE_API_KEY:
            try:
                context = f"Tu es l'assistant FactuScan. Tu aides avec les factures. Total: {total_ttc} DT. Invoices: {invoice_count}. Commande: {command}. Réponds court."
                model = genai.GenerativeModel('gemini-2.0-flash')
                response = model.generate_content(context)
                return jsonify({"response": response.text.strip()})
            except Exception as e:
                return jsonify({"response": f"Je comprends la commande '{command}', mais j'ai une erreur réseau. Le total est de {total_ttc} DT."})

        return jsonify({"response": f"Désolé, l'intelligence artificielle n'est pas configurée, mais je peux vous dire que vous avez {invoice_count} factures pour un total de {total_ttc:.2f} DT."})

    except Exception as e:
        return jsonify({"response": "Désolé, l'assistant est temporairement indisponible."})

@app.route('/voice/synthesize', methods=['POST'])
def synthesize_speech():
    """Convert text to speech"""
    data = request.get_json()
    text = data.get('text', '')
    
    try:
        from gtts import gTTS
        import tempfile
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
            tts = gTTS(text=text, lang='fr', slow=False)
            tts.save(tmp_file.name)
            
            # Read file and encode to base64
            with open(tmp_file.name, 'rb') as audio_file:
                audio_data = audio_file.read()
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            # Clean up temp file
            os.unlink(tmp_file.name)
            
            return jsonify({
                "audio": audio_base64,
                "format": "mp3"
            })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check_status', methods=['GET'])
def check_status():
    """Endpoint to check if the AI key and Database are correctly initialized"""
    return jsonify({
        "ai_active": GOOGLE_API_KEY is not None,
        "db_available": DB_AVAILABLE,
        "engine_type": "mysql" if "mysql" in str(engine) else "sqlite" if engine else "none",
        "key_preview": f"{GOOGLE_API_KEY[:4]}..." if GOOGLE_API_KEY else None
    })

# New Dashboard Routes
@app.route('/dashboard_adminlte')
@login_required
@admin_required
def dashboard_adminlte():
    """Serve the new AdminLTE-based dashboard"""
    return render_template('admin_dashboard.html')

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    db = get_db()
    if not db:
        return render_template('admin_dashboard.html', 
                               invoice_count=0, user_count=0, 
                               total_ttc=0, total_ht=0, total_vat=0,
                               ai_active=False)
                               
    invoice_count = int(db.query(func.count(Invoice.id)).scalar() or 0)
    user_count = int(db.query(func.count(User.id)).scalar() or 0)
    
    # Robustly handle sums and cast to float for template compatibility
    total_ttc = float(db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).scalar() or 0.0)
    total_ht = float(db.query(func.coalesce(func.sum(Invoice.ht_amount), 0.0)).scalar() or 0.0)
    total_vat = float(db.query(func.coalesce(func.sum(Invoice.vat_amount), 0.0)).scalar() or 0.0)
    
    # Fetch latest data for initial load widgets (index1.html / index2.html)
    recent_invoices = db.query(Invoice, User).outerjoin(User).order_by(Invoice.created_at.desc()).limit(7).all()
    latest_members = db.query(User).order_by(User.created_at.desc()).limit(8).all()
    
    return render_template('admin_dashboard.html', 
                           invoice_count=invoice_count, 
                           user_count=user_count, 
                           total_ttc=round(total_ttc, 2),
                           total_ht=round(total_ht, 2),
                           total_vat=round(total_vat, 2),
                           recent_invoices=recent_invoices,
                           latest_members=latest_members,
                           ai_active=GOOGLE_API_KEY is not None)

@app.route('/admin/messages')
@login_required
@admin_required
def admin_messages():
    """View all reclamations from users"""
    db = get_db()
    messages = db.query(Message, User).outerjoin(User).order_by(Message.timestamp.desc()).all()
    return render_template('admin/messages.html', messages=messages)

@app.route('/admin/api/messages/<int:msg_id>/status', methods=['PUT'])
@login_required
@admin_required
def admin_update_message_status(msg_id):
    data = request.get_json()
    new_status = data.get('status')
    
    if new_status not in ['new', 'read', 'resolved']:
        return jsonify({"error": "Status invalide"}), 400
        
    db = get_db()
    msg = db.get(Message, msg_id)
    if not msg:
        return jsonify({"error": "Message introuvable"}), 404
        
    msg.status = new_status
    db.commit()
    return jsonify({"message": f"Status mis à jour: {new_status}"}), 200

@app.route('/admin/api/messages/<int:msg_id>/reply', methods=['POST'])
@login_required
@admin_required
def admin_reply_message(msg_id):
    data = request.get_json()
    reply_text = data.get('reply')
    
    db = get_db()
    msg = db.get(Message, msg_id)
    if not msg:
        return jsonify({"error": "Message introuvable"}), 404
        
    msg.reply = reply_text
    msg.status = 'resolved'
    db.commit()
    
    # Notify admin dashboard to update the chat list
    socketio.emit('message_status_updated', {'id': msg_id, 'status': 'resolved'})
    
    return jsonify({"message": "Réponse envoyée et ticket résolu."}), 200

@app.route('/admin/api/chat_messages')
@login_required
@admin_required
def admin_api_chat_messages():
    """Get messages for the direct chat widget on dashboard"""
    db = get_db()
    if not db:
        return jsonify([]), 200
    try:
        # Use outerjoin to ensure messages load even if a user was deleted
        messages = db.query(Message, User).outerjoin(User).order_by(Message.timestamp.desc()).limit(10).all()
        result = []
        for m, u in messages:
            username = u.username if u else "Utilisateur supprimé"
            profile_img = u.profile_image if (u and u.profile_image) else 'default_avatar.png'
            result.append({
                "id": m.id,
                "user": username,
                "text": m.body,
                "time": m.timestamp.strftime('%H:%M') if m.timestamp else "--:--",
                "img": profile_img,
                "status": m.status,
                "reply": m.reply
            })
        return jsonify(result[::-1]), 200 # Return in chronological order
    except Exception as e:
        print(f"[CHAT ERROR] {e}")
        return jsonify([]), 500

@app.route('/admin')
@login_required
@admin_required
def admin_redirect():
    """Redirect /admin to /admin/dashboard"""
    return redirect(url_for('admin_dashboard'))

# Admin API Routes
@app.route('/admin/api/stats')
@login_required
@admin_required
def admin_api_stats():
    """Admin dashboard statistics"""
    db = get_db()
    if not db:
        return jsonify({"error": "Database unavailable"}), 503
    try:
        # 1. Base Totals
        total_invoices = int(db.query(func.count(Invoice.id)).scalar() or 0)
        total_users = int(db.query(func.count(User.id)).scalar() or 0)
        total_ttc = float(db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).scalar() or 0.0)
        total_ht = float(db.query(func.coalesce(func.sum(Invoice.ht_amount), 0.0)).scalar() or 0.0)
        total_vat = float(db.query(func.coalesce(func.sum(Invoice.vat_amount), 0.0)).scalar() or 0.0)

        # 2. Growth Calculation (Current Month vs Last Month)
        now = datetime.now()
        this_month_start = datetime(now.year, now.month, 1)
        last_month_end = this_month_start - timedelta(seconds=1)
        last_month_start = datetime(last_month_end.year, last_month_end.month, 1)

        curr_month_val = float(db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).filter(Invoice.created_at >= this_month_start).scalar() or 0.0)
        prev_month_val = float(db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).filter(Invoice.created_at >= last_month_start, Invoice.created_at <= last_month_end).scalar() or 0.0)
        
        growth_pct = 0
        if prev_month_val > 0:
            growth_pct = round(((curr_month_val - prev_month_val) / prev_month_val) * 100, 1)

        # 3. User distribution (for Donut Chart)
        dist_query = db.query(User.country, func.count(User.id)).group_by(User.country).all()
        user_distribution = {}
        for country, count in dist_query:
            # Aggregate first to prevent duplicate labels in chart legend
            label = str(country).strip() if (country and str(country).strip()) else "Inconnu"
            user_distribution[label] = user_distribution.get(label, 0) + int(count or 0)
            
        if not user_distribution:
            user_distribution = {"Aucune donnée": 0}
            
        pie_labels = list(user_distribution.keys())
        pie_series = list(user_distribution.values())

        # 3b. Pack distribution
        pack_query = db.query(User.subscription_type, func.count(User.id)).group_by(User.subscription_type).all()
        pack_distribution = {}
        for p_type, count in pack_query:
            label = str(p_type).strip() if p_type else "Basic"
            pack_distribution[label] = pack_distribution.get(label, 0) + int(count or 0)
        
        pack_labels = list(pack_distribution.keys())
        pack_series = list(pack_distribution.values())

        # 4. Latest Members (for index2.html widget)
        latest_members_query = db.query(User).order_by(User.created_at.desc()).limit(8).all()
        latest_members = []
        for u in latest_members_query:
            latest_members.append({
                "username": u.username,
                "img": u.profile_image or 'default_avatar.png',
                "date": u.created_at.strftime('%d %b') if u.created_at else "N/A"
            })

        # 5. Recent Invoices
        recent_invoices = []
        ri_query = db.query(Invoice, User).outerjoin(User).order_by(Invoice.created_at.desc()).limit(7).all()
        for i, u in ri_query:
            recent_invoices.append({
                "id": i.id, "number": i.invoice_number, "supplier": i.supplier or "Inconnu",
                "total": round(float(i.total_amount or 0.0), 2), "user": u.username if u else "System"
            })

        # 6. Daily stats for Revenue Chart (last 7 days)
        chart_labels = []
        chart_counts = []
        chart_sums = []
        chart_data_points = [] # For XY pair charts
        
        for i in range(6, -1, -1):
            day = datetime.now() - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            day_count = int(db.query(func.count(Invoice.id)).filter(
                Invoice.created_at >= day_start,
                Invoice.created_at <= day_end
            ).scalar() or 0)
            
            day_sum = float(db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).filter(
                Invoice.created_at >= day_start,
                Invoice.created_at <= day_end
            ).scalar() or 0.0)
            
            label = day.strftime('%a')
            chart_labels.append(label)
            chart_counts.append(day_count)
            chart_sums.append(round(day_sum, 2))
            chart_data_points.append({"x": label, "y": round(day_sum, 2)})

        return jsonify({
            "totals": {
                "invoices": total_invoices,
                "users": total_users,
                "ttc": round(total_ttc, 2),
                "total_amount": round(total_ttc, 2),
                "ht": round(total_ht, 2),
                "vat": round(total_vat, 2),
                "growth": growth_pct
            },
            "user_distribution": user_distribution,
            "pie_chart": {
                "labels": pie_labels,
                "series": pie_series
            },
            "pack_chart": {
                "labels": pack_labels,
                "series": pack_series
            },
            "latest_members": latest_members,
            "recent_invoices": recent_invoices,
            "chart": {
                "labels": chart_labels,
                "counts": chart_counts,
                "sums": chart_sums,
                "revenue": chart_sums, # Alias for ApexCharts
                "volume": chart_counts, # Alias for ApexCharts
                "data_points": chart_data_points,
                "series": [
                    {"name": "Revenu (DT)", "data": chart_sums},
                    {"name": "Volume (Factures)", "data": chart_counts}
                ]
            }
        }), 200
    except Exception as e:
        print(f"[ADMIN STATS ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/packs', methods=['GET'])
def api_get_packs():
    """Public API to get packs"""
    db = get_db()
    if not db: return jsonify([]), 200
    packs = db.query(Pack).all()
    return jsonify([{
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price_eur": p.price_eur,
        "price_tnd": p.price_tnd,
        "limit_text": p.limit_text,
        "features": json.loads(p.features_json) if p.features_json else [],
        "is_featured": p.is_featured
    } for p in packs])

@app.route('/admin/api/packs/<int:pack_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_pack(pack_id):
    """Update pack by admin"""
    db = get_db()
    pack = db.get(Pack, pack_id)
    if not pack: return jsonify({"error": "Pack non trouvé"}), 404
    data = request.get_json()

    try:
        if 'name' in data:
            # Vérifier si le nouveau nom n'est pas déjà pris par un autre pack
            existing = db.query(Pack).filter(Pack.name == data['name'], Pack.id != pack_id).first()
            if existing: return jsonify({"error": "Ce nom de pack est déjà utilisé"}), 400
            pack.name = data['name']
            
        pack.description = data.get('description', pack.description)
        
        # Gestion robuste des prix (remplacement des virgules par des points)
        def safe_float(val):
            if val is None or str(val).strip() == '': return 0.0
            return float(str(val).replace(',', '.'))
        
        pack.price_eur = safe_float(data.get('price_eur', pack.price_eur))
        pack.price_tnd = safe_float(data.get('price_tnd', pack.price_tnd))
        
        pack.limit_text = data.get('limit_text', pack.limit_text)
        if 'features' in data:
            pack.features_json = json.dumps(data['features'])
        pack.is_featured = bool(data.get('is_featured', pack.is_featured))
        
        db.commit()
        return jsonify({"message": "Pack mis à jour avec succès"}), 200
    except ValueError as ve:
        db.rollback()
        return jsonify({"error": f"Données de prix invalides: {str(ve)}"}), 400
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Erreur interne du serveur lors de la mise à jour du pack: {str(e)}"}), 500

@app.route('/admin/api/users')
@login_required
@admin_required
def admin_api_users():
    """Get all users for admin"""
    db = get_db()
    if not db:
        return jsonify([]), 200
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        result = []
        for u in users:
            result.append({
                "id": u.id,
                "username": u.username,
                "email": u.email or "",
                "role": u.role,
                "subscription": u.subscription_type,
                "is_authorized": u.is_authorized,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "full_name": u.full_name,
                "company_name": u.company_name,
                "city": u.city,
                "country": u.country,
                "profile_image": u.profile_image
            })
        return jsonify(result), 200
    except Exception as e:
        print(f"[ADMIN USERS ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def admin_api_update_user(user_id):
    """Update user by admin"""
    db = get_db()
    if not db:
        return jsonify({"error": "Database unavailable"}), 503
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    data = request.get_json()
    if 'role' in data:
        user.role = data['role']
    if 'subscription' in data:
        user.subscription_type = data['subscription']
    if 'is_authorized' in data:
        user.is_authorized = bool(data['is_authorized'])
    db.commit()
    return jsonify({"message": "User updated successfully"}), 200

@app.route('/admin/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_api_delete_user(user_id):
    """Delete user by admin"""
    db = get_db()
    if not db:
        return jsonify({"error": "Database unavailable"}), 503
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    db.delete(user)
    db.commit()
    return jsonify({"message": "User deleted successfully"}), 200

@app.route('/admin/api/notifications')
@login_required
@admin_required
def admin_api_notifications():
    """Get notification counts"""
    db = get_db()
    if not db:
        return jsonify({"total": 0, "new_invoices": 0, "new_users": 0}), 200
    try:
        day_ago = datetime.now() - timedelta(hours=24)
        new_invoices = db.query(func.count(Invoice.id)).filter(Invoice.created_at >= day_ago).scalar() or 0
        new_users = db.query(func.count(User.id)).filter(User.created_at >= day_ago).scalar() or 0
        new_messages = db.query(func.count(Message.id)).filter(Message.status == 'new').scalar() or 0
        return jsonify({
            "total": int(new_invoices + new_users + new_messages),
            "new_invoices": int(new_invoices),
            "new_users": int(new_users),
            "new_messages": int(new_messages)
        }), 200
    except Exception as e:
        print(f"[ADMIN NOTIFS ERROR] {e}")
        return jsonify({"total": 0, "new_invoices": 0, "new_users": 0}), 200

@app.route('/admin/api/recent_invoices')
@login_required
@admin_required
def admin_api_recent_invoices():
    """Get recent invoices for admin dropdown"""
    db = get_db()
    if not db:
        return jsonify([]), 200
    try:
        invoices = db.query(Invoice, User).outerjoin(User).order_by(Invoice.created_at.desc()).limit(10).all()
        result = []
        for i, u in invoices:
            result.append({
                "id": i.id,
                "invoice_number": i.invoice_number,
                "supplier": i.supplier or "Inconnu",
                "total_amount": float(i.total_amount or 0.0),
                "username": u.username if u else "Inconnu",
                "created_at": i.created_at.isoformat() if i.created_at else None
            })
        return jsonify(result), 200
    except Exception as e:
        print(f"[ADMIN RECENT ERROR] {e}")
        return jsonify([]), 200

@app.route('/api/invoices', methods=['GET'])
@login_required
def api_invoices():
    """API endpoint to get all invoices as JSON"""
    try:
        db = get_db()
        if not db:
            return jsonify([]), 200
        
        # Start with user-specific invoices by default
        query = db.query(Invoice).filter_by(user_id=current_user.id)
        
        # If the current user is an admin, they can see all invoices
        if current_user.role.lower() == 'admin':
            query = db.query(Invoice)
        invoices = query.order_by(Invoice.created_at.desc()).all()
        result = []
        for inv in invoices:
            result.append({
                'id': inv.id,
                'filename': inv.filename,
                'invoice_number': inv.invoice_number,
                'invoice_date': inv.invoice_date,
                'supplier': inv.supplier,
                'ice': inv.ice,
                'ht_amount': inv.ht_amount or 0,
                'vat_amount': inv.vat_amount or 0,
                'total_amount': inv.total_amount or 0,
                'created_at': inv.created_at.isoformat() if inv.created_at else None,
                'updated_at': inv.updated_at.isoformat() if inv.updated_at else None
            })
        return jsonify(result), 200
    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        return jsonify({"error": str(e)}), 500

# Global error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Ressource introuvable", "status": 404}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Erreur interne du serveur", "status": 500}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
# Fin du fichier - Déploiement Forcé
