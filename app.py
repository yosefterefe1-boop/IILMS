from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_
from datetime import datetime
from functools import wraps
import io

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    REPORTLAB = True
except ImportError:
    REPORTLAB = False

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'iilms-warehouse-secret-2024'
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access the IILMS.'


# ── Models ────────────────────────────────────────────────────────────────────

class User(db.Model, UserMixin):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    # roles: 'admin' | 'manager' | 'clerk' | 'sales'
    role          = db.Column(db.String(20), nullable=False, default='sales')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Equipment(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    sku            = db.Column(db.String(50), unique=True, nullable=False)
    name           = db.Column(db.String(100), nullable=False)
    category       = db.Column(db.String(100), nullable=False)
    specifications = db.Column(db.Text, nullable=True)
    qty            = db.Column(db.Integer, nullable=False)
    threshold      = db.Column(db.Integer, nullable=False, default=5)
    zone           = db.Column(db.String(20), nullable=False)
    aisle          = db.Column(db.String(20), nullable=False)
    shelf          = db.Column(db.String(20), nullable=False)

    @property
    def location(self):
        return f'{self.zone} / {self.aisle} / {self.shelf}'

    @property
    def status(self):
        if self.qty == 0:
            return 'Out of Stock'
        if self.qty <= self.threshold:
            return 'Low'
        return 'Normal'


class Transaction(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100))
    action    = db.Column(db.String(50))
    person    = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class AlertLog(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    item_id         = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=True)
    item_name       = db.Column(db.String(100))
    qty_at_alert    = db.Column(db.Integer)
    threshold       = db.Column(db.Integer)
    timestamp       = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged    = db.Column(db.Boolean, default=False)
    acknowledged_by = db.Column(db.String(100), nullable=True)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    item            = db.relationship('Equipment', backref='alerts', foreign_keys=[item_id])


# ── Auth helpers ──────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if current_user.role not in allowed_roles:
                flash('Access denied: you do not have permission for this action.')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Seed default data ─────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    if not User.query.first():
        for username, password, role in [
            ('admin',   'admin123',   'admin'),
            ('manager', 'manager123', 'manager'),
            ('clerk',   'clerk123',   'clerk'),
            ('sales',   'sales123',   'sales'),
        ]:
            u = User(username=username, role=role)
            u.set_password(password)
            db.session.add(u)

        for item in [
            Equipment(sku='EQ-001', name='Hydraulic Jack',    category='Tools',
                      specifications='5-ton capacity, 220V electric',
                      qty=12, threshold=3, zone='A', aisle='01', shelf='S1'),
            Equipment(sku='EQ-002', name='Safety Helmet',     category='PPE',
                      specifications='EN397 certified, adjustable harness',
                      qty=4,  threshold=10, zone='B', aisle='02', shelf='S3'),
            Equipment(sku='EQ-003', name='Forklift Battery',  category='Power',
                      specifications='48V 600Ah lead-acid',
                      qty=0,  threshold=2, zone='C', aisle='03', shelf='S2'),
            Equipment(sku='EQ-004', name='Safety Gloves',     category='PPE',
                      specifications='Cut-resistant Level 5',
                      qty=30, threshold=10, zone='B', aisle='02', shelf='S1'),
            Equipment(sku='EQ-005', name='Pallet Jack',       category='Tools',
                      specifications='2-ton manual hydraulic',
                      qty=3,  threshold=2, zone='A', aisle='03', shelf='S2'),
            Equipment(sku='EQ-006', name='Safety Vest',         category='PPE',
                      specifications='High-visibility ANSI Class 2, sizes M-XL',
                      qty=25, threshold=8,  zone='B', aisle='01', shelf='S2'),
            Equipment(sku='EQ-007', name='Safety Boots',        category='PPE',
                      specifications='Steel-toe, EN ISO 20345, sizes 38-47',
                      qty=18, threshold=5,  zone='B', aisle='01', shelf='S3'),
            Equipment(sku='EQ-008', name='Fire Extinguisher',   category='Safety',
                      specifications='CO2 5kg, class B/C, wall-mount bracket',
                      qty=10, threshold=3,  zone='D', aisle='01', shelf='S1'),
            Equipment(sku='EQ-009', name='First Aid Kit',       category='Safety',
                      specifications='50-person kit, OSHA compliant, wall-mount',
                      qty=6,  threshold=2,  zone='D', aisle='01', shelf='S2'),
            Equipment(sku='EQ-010', name='Angle Grinder',       category='Power Tools',
                      specifications='4.5 inch, 850W, 11000 RPM, 220V',
                      qty=8,  threshold=2,  zone='A', aisle='02', shelf='S1'),
            Equipment(sku='EQ-011', name='Electric Drill',      category='Power Tools',
                      specifications='13mm chuck, 700W, variable speed, 220V',
                      qty=10, threshold=3,  zone='A', aisle='02', shelf='S2'),
            Equipment(sku='EQ-012', name='Torque Wrench',       category='Tools',
                      specifications='1/2 inch drive, 20-200 Nm range',
                      qty=7,  threshold=2,  zone='A', aisle='01', shelf='S2'),
            Equipment(sku='EQ-013', name='Measuring Tape',      category='Tools',
                      specifications='10m steel tape, auto-lock, magnetic tip',
                      qty=20, threshold=5,  zone='A', aisle='04', shelf='S1'),
            Equipment(sku='EQ-014', name='Digital Multimeter',  category='Electronics',
                      specifications='Auto-ranging, AC/DC 1000V, 10A, CAT III',
                      qty=5,  threshold=2,  zone='E', aisle='01', shelf='S1'),
            Equipment(sku='EQ-015', name='Extension Cord',      category='Electrical',
                      specifications='20m, 3-pin, 16A, heavy-duty rubber',
                      qty=15, threshold=4,  zone='E', aisle='02', shelf='S1'),
            Equipment(sku='EQ-016', name='LED Work Light',      category='Electrical',
                      specifications='50W, 4500 lm, IP65, tripod stand',
                      qty=6,  threshold=2,  zone='E', aisle='02', shelf='S2'),
            Equipment(sku='EQ-017', name='Scaffold Tower',      category='Access',
                      specifications='3m working height, aluminium, 250kg load',
                      qty=2,  threshold=1,  zone='F', aisle='01', shelf='S1'),
            Equipment(sku='EQ-018', name='Step Ladder',         category='Access',
                      specifications='6-step fibreglass, 150kg rated, anti-slip',
                      qty=9,  threshold=3,  zone='F', aisle='01', shelf='S2'),
            Equipment(sku='EQ-019', name='Storage Rack',        category='Storage',
                      specifications='5-tier steel, 350kg per shelf, 200x90x45cm',
                      qty=4,  threshold=1,  zone='G', aisle='01', shelf='S1'),
            Equipment(sku='EQ-020', name='Plastic Bin',         category='Storage',
                      specifications='60L stackable polypropylene, 80kg capacity',
                      qty=50, threshold=10, zone='G', aisle='02', shelf='S1'),
            Equipment(sku='EQ-021', name='Hand Truck',          category='Tools',
                      specifications='200kg capacity, pneumatic tyres, folding',
                      qty=5,  threshold=2,  zone='A', aisle='03', shelf='S1'),
            Equipment(sku='EQ-022', name='Respirator Mask',     category='PPE',
                      specifications='Half-face P100, reusable, OV/P100 cartridge',
                      qty=14, threshold=5,  zone='B', aisle='03', shelf='S1'),
            Equipment(sku='EQ-023', name='Ear Defenders',       category='PPE',
                      specifications='SNR 33dB, adjustable headband, foldable',
                      qty=22, threshold=6,  zone='B', aisle='03', shelf='S2'),
            Equipment(sku='EQ-024', name='Safety Goggles',      category='PPE',
                      specifications='Anti-fog, anti-scratch, indirect ventilation',
                      qty=30, threshold=8,  zone='B', aisle='02', shelf='S2'),
            Equipment(sku='EQ-025', name='Welding Machine',     category='Power Tools',
                      specifications='MIG 200A, 220V, includes wire & gas hose',
                      qty=3,  threshold=1,  zone='C', aisle='01', shelf='S1'),
            Equipment(sku='EQ-026', name='Welding Helmet',      category='PPE',
                      specifications='Auto-darkening, DIN 9-13, solar powered',
                      qty=4,  threshold=2,  zone='B', aisle='04', shelf='S1'),
            Equipment(sku='EQ-027', name='Generator',           category='Power',
                      specifications='5kVA petrol, 220V/50Hz, electric start',
                      qty=2,  threshold=1,  zone='C', aisle='02', shelf='S1'),
            Equipment(sku='EQ-028', name='Air Compressor',      category='Power Tools',
                      specifications='50L tank, 2HP, 8 bar, direct drive',
                      qty=3,  threshold=1,  zone='C', aisle='02', shelf='S2'),
            Equipment(sku='EQ-029', name='Padlock',             category='Security',
                      specifications='50mm hardened steel shackle, keyed-alike set',
                      qty=40, threshold=10, zone='D', aisle='02', shelf='S1'),
            Equipment(sku='EQ-030', name='Barricade Tape',      category='Safety',
                      specifications='Yellow/black 75mm x 500m, PE, 3 rolls/box',
                      qty=12, threshold=3,  zone='D', aisle='03', shelf='S1'),
            # ── EQ-031 to EQ-060: Tools & Hand Tools ──────────────────────────
            Equipment(sku='EQ-031', name='Pipe Wrench',          category='Tools',
                      specifications='24 inch, cast iron jaw, heavy-duty',
                      qty=6,  threshold=2,  zone='A', aisle='01', shelf='S3'),
            Equipment(sku='EQ-032', name='Hacksaw',              category='Tools',
                      specifications='12 inch frame, bi-metal blade, adjustable',
                      qty=12, threshold=3,  zone='A', aisle='04', shelf='S2'),
            Equipment(sku='EQ-033', name='Screwdriver Set',      category='Tools',
                      specifications='10-piece Phillips/flathead, chrome-vanadium',
                      qty=15, threshold=4,  zone='A', aisle='04', shelf='S3'),
            Equipment(sku='EQ-034', name='Hammer',               category='Tools',
                      specifications='16 oz claw hammer, fibreglass handle',
                      qty=20, threshold=5,  zone='A', aisle='04', shelf='S4'),
            Equipment(sku='EQ-035', name='Sledgehammer',         category='Tools',
                      specifications='10 lb, 36 inch hickory handle',
                      qty=4,  threshold=1,  zone='A', aisle='05', shelf='S1'),
            Equipment(sku='EQ-036', name='Pliers Set',           category='Tools',
                      specifications='5-piece: needle-nose, combination, locking, etc.',
                      qty=10, threshold=3,  zone='A', aisle='04', shelf='S5'),
            Equipment(sku='EQ-037', name='Allen Key Set',        category='Tools',
                      specifications='Metric 1.5–19 mm, L-shape, 18-piece',
                      qty=12, threshold=3,  zone='A', aisle='05', shelf='S2'),
            Equipment(sku='EQ-038', name='Socket Set',           category='Tools',
                      specifications='72-piece 1/4 & 1/2 drive metric/imperial',
                      qty=7,  threshold=2,  zone='A', aisle='05', shelf='S3'),
            Equipment(sku='EQ-039', name='Wire Stripper',        category='Tools',
                      specifications='Self-adjusting, 0.2–6 mm², ergonomic grip',
                      qty=9,  threshold=2,  zone='E', aisle='03', shelf='S1'),
            Equipment(sku='EQ-040', name='Cable Cutter',         category='Tools',
                      specifications='Up to 70 mm² copper/aluminium cable',
                      qty=5,  threshold=2,  zone='E', aisle='03', shelf='S2'),
            Equipment(sku='EQ-041', name='Utility Knife',        category='Tools',
                      specifications='Retractable blade, rubber grip, spare blades x10',
                      qty=25, threshold=6,  zone='A', aisle='06', shelf='S1'),
            Equipment(sku='EQ-042', name='Chisel Set',           category='Tools',
                      specifications='6-piece cold chisel, octagonal handle, 6–25 mm',
                      qty=6,  threshold=2,  zone='A', aisle='06', shelf='S2'),
            Equipment(sku='EQ-043', name='Level',                category='Tools',
                      specifications='600 mm aluminium spirit level, 3 vials',
                      qty=8,  threshold=2,  zone='A', aisle='06', shelf='S3'),
            Equipment(sku='EQ-044', name='Tap & Die Set',        category='Tools',
                      specifications='40-piece metric M3–M12, HSS steel',
                      qty=4,  threshold=1,  zone='A', aisle='06', shelf='S4'),
            Equipment(sku='EQ-045', name='File Set',             category='Tools',
                      specifications='10-piece: flat, round, half-round, bastard cut',
                      qty=8,  threshold=2,  zone='A', aisle='07', shelf='S1'),
            Equipment(sku='EQ-046', name='Chain Block',          category='Lifting',
                      specifications='1-ton, 3m lift, Grade 80 chain',
                      qty=4,  threshold=1,  zone='H', aisle='01', shelf='S1'),
            Equipment(sku='EQ-047', name='Ratchet Strap',        category='Lifting',
                      specifications='5m x 25mm, 800kg WLL, J-hook ends',
                      qty=30, threshold=8,  zone='H', aisle='01', shelf='S2'),
            Equipment(sku='EQ-048', name='Wire Rope Sling',      category='Lifting',
                      specifications='6mm x 2m, 6x19 construction, 0.5t WLL',
                      qty=10, threshold=3,  zone='H', aisle='02', shelf='S1'),
            Equipment(sku='EQ-049', name='Shackle',              category='Lifting',
                      specifications='Bow shackle, 1t WLL, galvanised, M10',
                      qty=20, threshold=5,  zone='H', aisle='02', shelf='S2'),
            Equipment(sku='EQ-050', name='Trolley Jack',         category='Tools',
                      specifications='3-ton low-profile, quick-lift, steel',
                      qty=3,  threshold=1,  zone='A', aisle='03', shelf='S3'),
            Equipment(sku='EQ-051', name='Jack Stand',           category='Tools',
                      specifications='3-ton capacity, adjustable 290–430 mm, pair',
                      qty=6,  threshold=2,  zone='A', aisle='03', shelf='S4'),
            Equipment(sku='EQ-052', name='Bolt Cutter',          category='Tools',
                      specifications='24 inch, hardened jaws, cuts up to 12 mm rod',
                      qty=4,  threshold=1,  zone='A', aisle='07', shelf='S2'),
            Equipment(sku='EQ-053', name='Crow Bar',             category='Tools',
                      specifications='600 mm, high-carbon steel, flat/bent end',
                      qty=5,  threshold=2,  zone='A', aisle='07', shelf='S3'),
            Equipment(sku='EQ-054', name='Mallet',               category='Tools',
                      specifications='750g rubber mallet, fibreglass handle',
                      qty=10, threshold=3,  zone='A', aisle='07', shelf='S4'),
            Equipment(sku='EQ-055', name='Wheelbarrow',          category='Tools',
                      specifications='90L, steel tray, pneumatic tyre, 150kg load',
                      qty=4,  threshold=1,  zone='A', aisle='08', shelf='S1'),
            Equipment(sku='EQ-056', name='Workbench',            category='Tools',
                      specifications='1.2m steel top, 2 drawers, 500kg load',
                      qty=3,  threshold=1,  zone='A', aisle='08', shelf='S2'),
            Equipment(sku='EQ-057', name='Bench Vise',           category='Tools',
                      specifications='5 inch jaw, 127mm opening, swivel base',
                      qty=4,  threshold=1,  zone='A', aisle='08', shelf='S3'),
            Equipment(sku='EQ-058', name='Pipe Cutter',          category='Tools',
                      specifications='6–64 mm OD copper/steel, ratchet type',
                      qty=5,  threshold=2,  zone='A', aisle='09', shelf='S1'),
            Equipment(sku='EQ-059', name='Duct Tape',            category='Consumables',
                      specifications='50mm x 50m, silver, 200 micron, high-tack',
                      qty=40, threshold=10, zone='G', aisle='03', shelf='S1'),
            Equipment(sku='EQ-060', name='Cable Ties',           category='Consumables',
                      specifications='300 x 4.8mm, nylon PA66, 100/pack, black',
                      qty=60, threshold=15, zone='G', aisle='03', shelf='S2'),
            # ── EQ-061 to EQ-090: Power Tools & Electrical ────────────────────
            Equipment(sku='EQ-061', name='Circular Saw',         category='Power Tools',
                      specifications='185mm blade, 1400W, 5500 RPM, 220V',
                      qty=4,  threshold=1,  zone='A', aisle='02', shelf='S3'),
            Equipment(sku='EQ-062', name='Jigsaw',               category='Power Tools',
                      specifications='700W, orbital action, T-shank blades, 220V',
                      qty=3,  threshold=1,  zone='A', aisle='02', shelf='S4'),
            Equipment(sku='EQ-063', name='Reciprocating Saw',    category='Power Tools',
                      specifications='1050W, 28mm stroke, variable speed, 220V',
                      qty=3,  threshold=1,  zone='A', aisle='09', shelf='S2'),
            Equipment(sku='EQ-064', name='Bench Grinder',        category='Power Tools',
                      specifications='6 inch wheel, 200W, 2950 RPM, 220V',
                      qty=2,  threshold=1,  zone='A', aisle='09', shelf='S3'),
            Equipment(sku='EQ-065', name='Impact Wrench',        category='Power Tools',
                      specifications='1/2 inch, 680 Nm, 1800 RPM, 220V',
                      qty=4,  threshold=1,  zone='A', aisle='09', shelf='S4'),
            Equipment(sku='EQ-066', name='Heat Gun',             category='Power Tools',
                      specifications='2000W, 50–600°C, 2 speed, 220V',
                      qty=5,  threshold=2,  zone='A', aisle='10', shelf='S1'),
            Equipment(sku='EQ-067', name='Electric Sander',      category='Power Tools',
                      specifications='Random-orbit 125mm, 300W, variable speed',
                      qty=4,  threshold=1,  zone='A', aisle='10', shelf='S2'),
            Equipment(sku='EQ-068', name='Rotary Hammer',        category='Power Tools',
                      specifications='SDS-Plus, 800W, 3-mode, 3.0J, 220V',
                      qty=4,  threshold=1,  zone='A', aisle='10', shelf='S3'),
            Equipment(sku='EQ-069', name='Cable Reel',           category='Electrical',
                      specifications='40m, 4-way socket, 16A, IP44, retractable',
                      qty=8,  threshold=2,  zone='E', aisle='04', shelf='S1'),
            Equipment(sku='EQ-070', name='Junction Box',         category='Electrical',
                      specifications='IP65, 150x110x70mm, polycarbonate, DIN rail',
                      qty=15, threshold=4,  zone='E', aisle='04', shelf='S2'),
            Equipment(sku='EQ-071', name='MCB Breaker',          category='Electrical',
                      specifications='32A single-pole, 6kA breaking capacity, DIN',
                      qty=20, threshold=5,  zone='E', aisle='04', shelf='S3'),
            Equipment(sku='EQ-072', name='Conduit Pipe',         category='Electrical',
                      specifications='25mm PVC, 3m length, grey, pack of 10',
                      qty=30, threshold=8,  zone='E', aisle='05', shelf='S1'),
            Equipment(sku='EQ-073', name='Wire Loom',            category='Electrical',
                      specifications='10mm split loom, 10m roll, polyethylene',
                      qty=20, threshold=5,  zone='E', aisle='05', shelf='S2'),
            Equipment(sku='EQ-074', name='Crimping Tool',        category='Electrical',
                      specifications='Ratchet, 0.5–16 mm², insulated terminals',
                      qty=6,  threshold=2,  zone='E', aisle='03', shelf='S3'),
            Equipment(sku='EQ-075', name='Clamp Meter',          category='Electronics',
                      specifications='AC/DC 600A, True RMS, jaw 40mm, CAT IV',
                      qty=4,  threshold=1,  zone='E', aisle='01', shelf='S2'),
            Equipment(sku='EQ-076', name='Insulation Tester',    category='Electronics',
                      specifications='1000V, 0.1 MΩ–20 GΩ, PI/DAR function',
                      qty=2,  threshold=1,  zone='E', aisle='01', shelf='S3'),
            Equipment(sku='EQ-077', name='Oscilloscope',         category='Electronics',
                      specifications='2-channel, 50 MHz, 1 GSa/s, 7 inch display',
                      qty=1,  threshold=1,  zone='E', aisle='01', shelf='S4'),
            Equipment(sku='EQ-078', name='Soldering Iron',       category='Electronics',
                      specifications='60W, adjustable 200–480°C, ceramic heater',
                      qty=5,  threshold=2,  zone='E', aisle='06', shelf='S1'),
            Equipment(sku='EQ-079', name='Soldering Station',    category='Electronics',
                      specifications='48W digital, ESD-safe, 200–480°C, 220V',
                      qty=2,  threshold=1,  zone='E', aisle='06', shelf='S2'),
            Equipment(sku='EQ-080', name='UPS Battery',          category='Power',
                      specifications='12V 7Ah VRLA, F2 terminal, cycle-use',
                      qty=10, threshold=3,  zone='C', aisle='03', shelf='S1'),
            Equipment(sku='EQ-081', name='Solar Panel',          category='Power',
                      specifications='100W monocrystalline, 18V, IP65, 1010x660mm',
                      qty=5,  threshold=1,  zone='C', aisle='03', shelf='S2'),
            Equipment(sku='EQ-082', name='Battery Charger',      category='Power',
                      specifications='24V 30A, automatic, temperature compensated',
                      qty=4,  threshold=1,  zone='C', aisle='04', shelf='S1'),
            Equipment(sku='EQ-083', name='Inverter',             category='Power',
                      specifications='2000W pure sine wave, 24V DC to 220V AC',
                      qty=2,  threshold=1,  zone='C', aisle='04', shelf='S2'),
            Equipment(sku='EQ-084', name='Diesel Jerry Can',     category='Fuel',
                      specifications='20L HDPE, UN approved, red, sealed cap',
                      qty=10, threshold=3,  zone='C', aisle='05', shelf='S1'),
            Equipment(sku='EQ-085', name='Funnel',               category='Fuel',
                      specifications='Flexible 30cm, 250ml, chemical-resistant',
                      qty=8,  threshold=2,  zone='C', aisle='05', shelf='S2'),
            Equipment(sku='EQ-086', name='Oil Drain Pan',        category='Fuel',
                      specifications='12L polypropylene, pour spout, handle',
                      qty=5,  threshold=2,  zone='C', aisle='05', shelf='S3'),
            Equipment(sku='EQ-087', name='Grease Gun',           category='Tools',
                      specifications='400cc lever-action, 1/8 NPT, Zerk fitting',
                      qty=6,  threshold=2,  zone='A', aisle='11', shelf='S1'),
            Equipment(sku='EQ-088', name='Oil Can',              category='Tools',
                      specifications='500ml trigger-pump, flexible nozzle, steel',
                      qty=8,  threshold=2,  zone='A', aisle='11', shelf='S2'),
            Equipment(sku='EQ-089', name='Pressure Gauge',       category='Measurement',
                      specifications='0–16 bar, Ø63 glycerine, 1/4 BSP bottom',
                      qty=10, threshold=3,  zone='I', aisle='01', shelf='S1'),
            Equipment(sku='EQ-090', name='Flow Meter',           category='Measurement',
                      specifications='1 inch inline turbine, 1–30 L/min, pulse out',
                      qty=3,  threshold=1,  zone='I', aisle='01', shelf='S2'),
            # ── EQ-091 to EQ-120: PPE & Safety ───────────────────────────────
            Equipment(sku='EQ-091', name='Face Shield',          category='PPE',
                      specifications='Clear polycarbonate, 180° coverage, ratchet',
                      qty=12, threshold=4,  zone='B', aisle='04', shelf='S2'),
            Equipment(sku='EQ-092', name='Knee Pads',            category='PPE',
                      specifications='Gel insert, adjustable straps, EN 14404',
                      qty=15, threshold=4,  zone='B', aisle='05', shelf='S1'),
            Equipment(sku='EQ-093', name='Fall Arrest Harness',  category='PPE',
                      specifications='Full-body, EN 361, 140kg max, dorsal D-ring',
                      qty=6,  threshold=2,  zone='B', aisle='05', shelf='S2'),
            Equipment(sku='EQ-094', name='Lanyard',              category='PPE',
                      specifications='1.8m energy-absorbing, EN 355, snap hooks',
                      qty=8,  threshold=2,  zone='B', aisle='05', shelf='S3'),
            Equipment(sku='EQ-095', name='Earplugs',             category='PPE',
                      specifications='Foam 33dB SNR, corded, 200 pairs/box',
                      qty=10, threshold=3,  zone='B', aisle='06', shelf='S1'),
            Equipment(sku='EQ-096', name='Nitrile Gloves',       category='PPE',
                      specifications='Powder-free, 0.1mm, sizes S-XL, 100/box',
                      qty=20, threshold=5,  zone='B', aisle='06', shelf='S2'),
            Equipment(sku='EQ-097', name='Chemical Suit',        category='PPE',
                      specifications='Type 5/6, microporous, EN 13982, M-XXL',
                      qty=8,  threshold=2,  zone='B', aisle='06', shelf='S3'),
            Equipment(sku='EQ-098', name='Spill Kit',            category='Safety',
                      specifications='30L oil-only absorbent, pads/socks/pillows',
                      qty=5,  threshold=2,  zone='D', aisle='04', shelf='S1'),
            Equipment(sku='EQ-099', name='Eye Wash Station',     category='Safety',
                      specifications='Portable 1L sealed saline, ANSI Z358.1',
                      qty=4,  threshold=1,  zone='D', aisle='04', shelf='S2'),
            Equipment(sku='EQ-100', name='Safety Sign',          category='Safety',
                      specifications='ISO 7010, rigid PVC 200x150mm, self-adhesive',
                      qty=50, threshold=10, zone='D', aisle='05', shelf='S1'),
            Equipment(sku='EQ-101', name='Fire Blanket',         category='Safety',
                      specifications='1.2x1.2m fibreglass, BS EN 1869, quick-release',
                      qty=6,  threshold=2,  zone='D', aisle='05', shelf='S2'),
            Equipment(sku='EQ-102', name='Smoke Detector',       category='Safety',
                      specifications='Photoelectric, 9V battery, EN 14604',
                      qty=8,  threshold=2,  zone='D', aisle='05', shelf='S3'),
            Equipment(sku='EQ-103', name='Emergency Light',      category='Safety',
                      specifications='3-hour, LED, maintained/non-maintained, 220V',
                      qty=6,  threshold=2,  zone='D', aisle='06', shelf='S1'),
            Equipment(sku='EQ-104', name='Defibrillator',        category='Safety',
                      specifications='AED, semi-auto, bilingual voice, IP55',
                      qty=1,  threshold=1,  zone='D', aisle='06', shelf='S2'),
            Equipment(sku='EQ-105', name='Stretcher',            category='Safety',
                      specifications='Folding, aluminium frame, 150kg capacity',
                      qty=2,  threshold=1,  zone='D', aisle='06', shelf='S3'),
            Equipment(sku='EQ-106', name='Oxygen Cylinder',      category='Safety',
                      specifications='5L medical O2, 200 bar, with regulator',
                      qty=2,  threshold=1,  zone='D', aisle='07', shelf='S1'),
            Equipment(sku='EQ-107', name='Gas Detector',         category='Safety',
                      specifications='4-gas LEL/O2/CO/H2S, datalogging, IP67',
                      qty=4,  threshold=1,  zone='D', aisle='07', shelf='S2'),
            Equipment(sku='EQ-108', name='Lockout Kit',          category='Safety',
                      specifications='14-piece LOTO set, padlocks, hasps, tags',
                      qty=5,  threshold=2,  zone='D', aisle='07', shelf='S3'),
            Equipment(sku='EQ-109', name='Traffic Cone',         category='Safety',
                      specifications='750mm, PVC, weighted base, retro-reflective',
                      qty=20, threshold=5,  zone='D', aisle='08', shelf='S1'),
            Equipment(sku='EQ-110', name='Speed Bump',           category='Safety',
                      specifications='50mm rubber, 500mm section, yellow, bolt-down',
                      qty=8,  threshold=2,  zone='D', aisle='08', shelf='S2'),
            Equipment(sku='EQ-111', name='Wheel Chock',          category='Safety',
                      specifications='Heavy-duty rubber, 200x200x100mm, pair',
                      qty=10, threshold=3,  zone='D', aisle='08', shelf='S3'),
            Equipment(sku='EQ-112', name='Safety Rope',          category='Safety',
                      specifications='12mm kernmantle, 50m, EN 1891, orange',
                      qty=4,  threshold=1,  zone='D', aisle='09', shelf='S1'),
            Equipment(sku='EQ-113', name='Rescue Bag',           category='Safety',
                      specifications='Throw bag 15m, 8mm polypropylene, 25m range',
                      qty=2,  threshold=1,  zone='D', aisle='09', shelf='S2'),
            Equipment(sku='EQ-114', name='Carabiner',            category='PPE',
                      specifications='Steel, 25kN gate 7kN, screw-lock, EN 362',
                      qty=15, threshold=4,  zone='B', aisle='07', shelf='S1'),
            Equipment(sku='EQ-115', name='Helmet Lamp',          category='PPE',
                      specifications='LED 200lm, clip-on, IPX4, 3xAAA',
                      qty=10, threshold=3,  zone='B', aisle='07', shelf='S2'),
            Equipment(sku='EQ-116', name='Anti-Fatigue Mat',     category='Safety',
                      specifications='90x60cm, 12mm foam, beveled edge, black',
                      qty=8,  threshold=2,  zone='D', aisle='09', shelf='S3'),
            Equipment(sku='EQ-117', name='Insulating Mat',       category='Electrical',
                      specifications='1m x 1m, 11kV rated, Class 2, red rubber',
                      qty=4,  threshold=1,  zone='E', aisle='07', shelf='S1'),
            Equipment(sku='EQ-118', name='Voltage Tester',       category='Electrical',
                      specifications='Non-contact 12–1000V AC, audible/visual',
                      qty=8,  threshold=2,  zone='E', aisle='07', shelf='S2'),
            Equipment(sku='EQ-119', name='Phase Tester',         category='Electrical',
                      specifications='3-phase rotation indicator, 100–600V, 50/60Hz',
                      qty=3,  threshold=1,  zone='E', aisle='07', shelf='S3'),
            Equipment(sku='EQ-120', name='Earthing Kit',         category='Electrical',
                      specifications='Portable 3-phase, 11kV rated, 6mm² copper',
                      qty=2,  threshold=1,  zone='E', aisle='08', shelf='S1'),
            # ── EQ-121 to EQ-150: Storage, Packaging & Material Handling ──────
            Equipment(sku='EQ-121', name='Pallet',               category='Storage',
                      specifications='1200x1000mm, EUR standard, 1500kg dynamic',
                      qty=40, threshold=10, zone='G', aisle='04', shelf='S1'),
            Equipment(sku='EQ-122', name='Pallet Wrap',          category='Packaging',
                      specifications='500mm x 300m, 23 micron stretch film',
                      qty=20, threshold=5,  zone='G', aisle='04', shelf='S2'),
            Equipment(sku='EQ-123', name='Strapping Machine',    category='Packaging',
                      specifications='Semi-auto, 12mm PP strap, 220V, table-top',
                      qty=1,  threshold=1,  zone='G', aisle='05', shelf='S1'),
            Equipment(sku='EQ-124', name='Bubble Wrap',          category='Packaging',
                      specifications='500mm x 100m roll, 10mm bubble, perforated',
                      qty=10, threshold=3,  zone='G', aisle='05', shelf='S2'),
            Equipment(sku='EQ-125', name='Cardboard Box',        category='Packaging',
                      specifications='600x400x400mm, double-wall, pack of 20',
                      qty=15, threshold=4,  zone='G', aisle='05', shelf='S3'),
            Equipment(sku='EQ-126', name='Label Printer',        category='Storage',
                      specifications='Thermal direct 203dpi, 104mm, USB/LAN',
                      qty=2,  threshold=1,  zone='G', aisle='06', shelf='S1'),
            Equipment(sku='EQ-127', name='Label Roll',           category='Consumables',
                      specifications='100x150mm thermal, 500 labels/roll, direct',
                      qty=30, threshold=8,  zone='G', aisle='06', shelf='S2'),
            Equipment(sku='EQ-128', name='Barcode Scanner',      category='Electronics',
                      specifications='1D/2D, USB, IP42, 3mil resolution, trigger',
                      qty=4,  threshold=1,  zone='G', aisle='06', shelf='S3'),
            Equipment(sku='EQ-129', name='Weighing Scale',       category='Measurement',
                      specifications='300kg platform scale, 100g resolution, RS232',
                      qty=2,  threshold=1,  zone='I', aisle='02', shelf='S1'),
            Equipment(sku='EQ-130', name='Bench Scale',          category='Measurement',
                      specifications='30kg x 1g, stainless pan, OIML R76, RS232',
                      qty=3,  threshold=1,  zone='I', aisle='02', shelf='S2'),
            Equipment(sku='EQ-131', name='Forklift',             category='Machinery',
                      specifications='3-ton LPG sit-down, 4.8m lift, Hyundai',
                      qty=2,  threshold=1,  zone='J', aisle='01', shelf='S1'),
            Equipment(sku='EQ-132', name='Reach Truck',          category='Machinery',
                      specifications='1.6-ton electric, 9.5m lift, side shift',
                      qty=1,  threshold=1,  zone='J', aisle='01', shelf='S2'),
            Equipment(sku='EQ-133', name='Order Picker',         category='Machinery',
                      specifications='1-ton, 6m pick height, electric, stand-on',
                      qty=1,  threshold=1,  zone='J', aisle='02', shelf='S1'),
            Equipment(sku='EQ-134', name='Scissor Lift',         category='Access',
                      specifications='Elec, 8m working height, 450kg, 1.2m ext deck',
                      qty=1,  threshold=1,  zone='F', aisle='02', shelf='S1'),
            Equipment(sku='EQ-135', name='Boom Lift',            category='Access',
                      specifications='Diesel, 20m working height, 4WD, 230kg',
                      qty=1,  threshold=1,  zone='F', aisle='02', shelf='S2'),
            Equipment(sku='EQ-136', name='Platform Trolley',     category='Tools',
                      specifications='600x900mm, 300kg, 4 swivel castors, steel',
                      qty=6,  threshold=2,  zone='A', aisle='12', shelf='S1'),
            Equipment(sku='EQ-137', name='Drum Trolley',         category='Tools',
                      specifications='Vertical 200L steel drum, 350kg, rubber strap',
                      qty=3,  threshold=1,  zone='A', aisle='12', shelf='S2'),
            Equipment(sku='EQ-138', name='Stacker',              category='Machinery',
                      specifications='Manual, 1-ton, 2.5m lift, fork width 540mm',
                      qty=2,  threshold=1,  zone='J', aisle='02', shelf='S2'),
            Equipment(sku='EQ-139', name='Conveyor Belt',        category='Machinery',
                      specifications='3m x 500mm PVC belt, 0.1 m/s, 220V, 100kg',
                      qty=1,  threshold=1,  zone='J', aisle='03', shelf='S1'),
            Equipment(sku='EQ-140', name='Shrink Wrap Machine',  category='Packaging',
                      specifications='I-bar sealer + heat tunnel, 220V, 400mm web',
                      qty=1,  threshold=1,  zone='G', aisle='07', shelf='S1'),
            Equipment(sku='EQ-141', name='Tape Dispenser Gun',   category='Packaging',
                      specifications='Hand-held, fits 48mm wide tape roll, comfort grip',
                      qty=10, threshold=3,  zone='G', aisle='07', shelf='S2'),
            Equipment(sku='EQ-142', name='Packing Tape',         category='Consumables',
                      specifications='48mm x 100m, transparent, acrylic adhesive',
                      qty=50, threshold=12, zone='G', aisle='07', shelf='S3'),
            Equipment(sku='EQ-143', name='Foam Padding',         category='Packaging',
                      specifications='1m x 2m x 50mm, closed-cell PE, charcoal',
                      qty=8,  threshold=2,  zone='G', aisle='08', shelf='S1'),
            Equipment(sku='EQ-144', name='Desiccant Pack',       category='Consumables',
                      specifications='Silica gel 50g, humidity indicator, 100/carton',
                      qty=20, threshold=5,  zone='G', aisle='08', shelf='S2'),
            Equipment(sku='EQ-145', name='Cargo Net',            category='Lifting',
                      specifications='3x4m, 50mm mesh, 1000kg SWL, corner rings',
                      qty=4,  threshold=1,  zone='H', aisle='03', shelf='S1'),
            Equipment(sku='EQ-146', name='Load Cell',            category='Measurement',
                      specifications='5-ton compression, IP67, mV/V output, M16',
                      qty=2,  threshold=1,  zone='I', aisle='03', shelf='S1'),
            Equipment(sku='EQ-147', name='Crane Scale',          category='Measurement',
                      specifications='2000kg, 0.5kg resolution, LCD, shackle mount',
                      qty=2,  threshold=1,  zone='I', aisle='03', shelf='S2'),
            Equipment(sku='EQ-148', name='Vernier Caliper',      category='Measurement',
                      specifications='150mm, 0.02mm resolution, stainless, digital',
                      qty=6,  threshold=2,  zone='I', aisle='04', shelf='S1'),
            Equipment(sku='EQ-149', name='Micrometer',           category='Measurement',
                      specifications='0–25mm, 0.001mm resolution, ratchet thimble',
                      qty=4,  threshold=1,  zone='I', aisle='04', shelf='S2'),
            Equipment(sku='EQ-150', name='Laser Distance Meter', category='Measurement',
                      specifications='100m range, ±1.5mm accuracy, IP54, Bluetooth',
                      qty=3,  threshold=1,  zone='I', aisle='04', shelf='S3'),
            # ── EQ-151 to EQ-200: Cleaning, HVAC, Plumbing & Miscellaneous ───
            Equipment(sku='EQ-151', name='Pressure Washer',      category='Cleaning',
                      specifications='2200W, 150 bar, 420 L/h, 5m hose, 220V',
                      qty=2,  threshold=1,  zone='K', aisle='01', shelf='S1'),
            Equipment(sku='EQ-152', name='Industrial Vacuum',    category='Cleaning',
                      specifications='30L, 1400W, wet/dry, HEPA filter, 220V',
                      qty=3,  threshold=1,  zone='K', aisle='01', shelf='S2'),
            Equipment(sku='EQ-153', name='Floor Sweeper',        category='Cleaning',
                      specifications='Battery, 85cm brush width, 10000 m²/h, 24V',
                      qty=1,  threshold=1,  zone='K', aisle='02', shelf='S1'),
            Equipment(sku='EQ-154', name='Mop Set',              category='Cleaning',
                      specifications='Kentucky cotton mop + wringer bucket, 15L',
                      qty=6,  threshold=2,  zone='K', aisle='02', shelf='S2'),
            Equipment(sku='EQ-155', name='Cleaning Cart',        category='Cleaning',
                      specifications='3-shelf aluminium, 600x900mm, 4 swivel castors',
                      qty=3,  threshold=1,  zone='K', aisle='02', shelf='S3'),
            Equipment(sku='EQ-156', name='Floor Scrubber',       category='Cleaning',
                      specifications='Walk-behind 45cm disc, 900W, 220V, 35L tank',
                      qty=1,  threshold=1,  zone='K', aisle='03', shelf='S1'),
            Equipment(sku='EQ-157', name='Degreaser',            category='Cleaning',
                      specifications='5L spray bottle, industrial alkaline, pH 12',
                      qty=15, threshold=4,  zone='K', aisle='03', shelf='S2'),
            Equipment(sku='EQ-158', name='Absorbent Granules',   category='Cleaning',
                      specifications='25kg bag, clay-based, 15L absorption/kg',
                      qty=10, threshold=3,  zone='K', aisle='03', shelf='S3'),
            Equipment(sku='EQ-159', name='Waste Bin',            category='Cleaning',
                      specifications='120L HDPE wheelie bin, foot-pedal lid, grey',
                      qty=10, threshold=3,  zone='K', aisle='04', shelf='S1'),
            Equipment(sku='EQ-160', name='Recycling Bin Set',    category='Cleaning',
                      specifications='3x60L colour-coded bins + signs, plastic',
                      qty=4,  threshold=1,  zone='K', aisle='04', shelf='S2'),
            Equipment(sku='EQ-161', name='Air Conditioner',      category='HVAC',
                      specifications='Split 18000 BTU, inverter, R32, 220V',
                      qty=2,  threshold=1,  zone='L', aisle='01', shelf='S1'),
            Equipment(sku='EQ-162', name='Portable Fan',         category='HVAC',
                      specifications='Axial 600mm, 250W, 3-speed, 220V, industrial',
                      qty=5,  threshold=2,  zone='L', aisle='01', shelf='S2'),
            Equipment(sku='EQ-163', name='Exhaust Fan',          category='HVAC',
                      specifications='450mm wall-mount, 200W, 3000 m³/h, 220V',
                      qty=3,  threshold=1,  zone='L', aisle='02', shelf='S1'),
            Equipment(sku='EQ-164', name='Dehumidifier',         category='HVAC',
                      specifications='50L/day, auto defrost, continuous drain, 220V',
                      qty=2,  threshold=1,  zone='L', aisle='02', shelf='S2'),
            Equipment(sku='EQ-165', name='Air Duster',           category='HVAC',
                      specifications='400ml compressed air canister, plastic nozzle',
                      qty=20, threshold=5,  zone='L', aisle='03', shelf='S1'),
            Equipment(sku='EQ-166', name='Hygrometer',           category='Measurement',
                      specifications='Digital T&H, ±0.5°C ±3% RH, data-log, USB',
                      qty=5,  threshold=2,  zone='I', aisle='05', shelf='S1'),
            Equipment(sku='EQ-167', name='Thermometer Gun',      category='Measurement',
                      specifications='IR -50 to 550°C, ±1.5%, D:S 12:1, laser',
                      qty=4,  threshold=1,  zone='I', aisle='05', shelf='S2'),
            Equipment(sku='EQ-168', name='Anemometer',           category='Measurement',
                      specifications='0.3–45 m/s, ±3%, temp sensor, data-log',
                      qty=2,  threshold=1,  zone='I', aisle='05', shelf='S3'),
            Equipment(sku='EQ-169', name='Lux Meter',            category='Measurement',
                      specifications='0–200000 lux, ±3%, cosine-corrected sensor',
                      qty=2,  threshold=1,  zone='I', aisle='06', shelf='S1'),
            Equipment(sku='EQ-170', name='Noise Meter',          category='Measurement',
                      specifications='30–130 dB, ±1.5 dB, A/C weight, data-log',
                      qty=2,  threshold=1,  zone='I', aisle='06', shelf='S2'),
            Equipment(sku='EQ-171', name='Water Pump',           category='Plumbing',
                      specifications='Centrifugal 1HP, 50 L/min, 30m head, 220V',
                      qty=2,  threshold=1,  zone='M', aisle='01', shelf='S1'),
            Equipment(sku='EQ-172', name='Submersible Pump',     category='Plumbing',
                      specifications='400W, 10 m³/h, 7m head, 220V, IP68',
                      qty=2,  threshold=1,  zone='M', aisle='01', shelf='S2'),
            Equipment(sku='EQ-173', name='Pipe Fittings Kit',    category='Plumbing',
                      specifications='80-piece BSP/NPT galvanised, 1/4–2 inch',
                      qty=3,  threshold=1,  zone='M', aisle='02', shelf='S1'),
            Equipment(sku='EQ-174', name='PTFE Tape',            category='Plumbing',
                      specifications='12mm x 12m, white, 0.1mm, pack of 10',
                      qty=30, threshold=8,  zone='M', aisle='02', shelf='S2'),
            Equipment(sku='EQ-175', name='Gate Valve',           category='Plumbing',
                      specifications='2 inch, PN16, bronze, rising spindle, BSP',
                      qty=5,  threshold=2,  zone='M', aisle='03', shelf='S1'),
            Equipment(sku='EQ-176', name='Ball Valve',           category='Plumbing',
                      specifications='1 inch, PN40, stainless 316, full-bore, lever',
                      qty=10, threshold=3,  zone='M', aisle='03', shelf='S2'),
            Equipment(sku='EQ-177', name='Hose Pipe',            category='Plumbing',
                      specifications='3/4 inch x 20m, reinforced PVC, 12 bar',
                      qty=8,  threshold=2,  zone='M', aisle='04', shelf='S1'),
            Equipment(sku='EQ-178', name='Nozzle Spray',         category='Plumbing',
                      specifications='Adjustable cone/fan/jet, 3/4 BSP, zinc',
                      qty=10, threshold=3,  zone='M', aisle='04', shelf='S2'),
            Equipment(sku='EQ-179', name='Pipe Insulation',      category='Plumbing',
                      specifications='19mm wall, 22mm bore, 1m length, nitrile',
                      qty=20, threshold=5,  zone='M', aisle='05', shelf='S1'),
            Equipment(sku='EQ-180', name='Sump Pump',            category='Plumbing',
                      specifications='Stainless float switch, 700W, 12000 L/h',
                      qty=1,  threshold=1,  zone='M', aisle='05', shelf='S2'),
            Equipment(sku='EQ-181', name='Walkie-Talkie',        category='Communication',
                      specifications='5W UHF, 16ch, 10km range, IP54, USB charge',
                      qty=10, threshold=3,  zone='N', aisle='01', shelf='S1'),
            Equipment(sku='EQ-182', name='Two-Way Radio',        category='Communication',
                      specifications='Digital DMR, 4W, 128ch, Bluetooth, IP67',
                      qty=4,  threshold=2,  zone='N', aisle='01', shelf='S2'),
            Equipment(sku='EQ-183', name='Intercom System',      category='Communication',
                      specifications='4-station, wired, 220V, hands-free, door button',
                      qty=1,  threshold=1,  zone='N', aisle='02', shelf='S1'),
            Equipment(sku='EQ-184', name='CCTV Camera',          category='Security',
                      specifications='4MP IP dome, IR 30m, H.265+, PoE, 2.8mm',
                      qty=6,  threshold=2,  zone='N', aisle='02', shelf='S2'),
            Equipment(sku='EQ-185', name='NVR Recorder',         category='Security',
                      specifications='8-channel PoE, 4K, 4TB HDD, HDMI, remote',
                      qty=1,  threshold=1,  zone='N', aisle='02', shelf='S3'),
            Equipment(sku='EQ-186', name='Access Control Panel', category='Security',
                      specifications='4-door controller, TCP/IP, 100k card cap',
                      qty=1,  threshold=1,  zone='N', aisle='03', shelf='S1'),
            Equipment(sku='EQ-187', name='RFID Card',            category='Security',
                      specifications='MIFARE 13.56 MHz, 1k, ISO 14443A, pack 50',
                      qty=5,  threshold=2,  zone='N', aisle='03', shelf='S2'),
            Equipment(sku='EQ-188', name='Alarm Siren',          category='Security',
                      specifications='Outdoor piezo, 120dB, 12V DC, weatherproof',
                      qty=3,  threshold=1,  zone='N', aisle='03', shelf='S3'),
            Equipment(sku='EQ-189', name='Laptop Computer',      category='Electronics',
                      specifications='15.6 inch, i5, 16GB RAM, 512GB SSD, Win 11',
                      qty=3,  threshold=1,  zone='E', aisle='09', shelf='S1'),
            Equipment(sku='EQ-190', name='Tablet',               category='Electronics',
                      specifications='10 inch, Android 13, 4GB/64GB, 4G, IP65',
                      qty=4,  threshold=1,  zone='E', aisle='09', shelf='S2'),
            Equipment(sku='EQ-191', name='Printer',              category='Electronics',
                      specifications='A4 laser mono, 30 ppm, duplex, LAN/USB',
                      qty=2,  threshold=1,  zone='E', aisle='09', shelf='S3'),
            Equipment(sku='EQ-192', name='Network Switch',       category='Electronics',
                      specifications='24-port GbE, unmanaged, rack-mount, 220V',
                      qty=2,  threshold=1,  zone='E', aisle='10', shelf='S1'),
            Equipment(sku='EQ-193', name='UPS Unit',             category='Power',
                      specifications='1000VA/600W, AVR, 6 outlets, LCD, 220V',
                      qty=3,  threshold=1,  zone='C', aisle='06', shelf='S1'),
            Equipment(sku='EQ-194', name='Paint Sprayer',        category='Power Tools',
                      specifications='HVLP 400W, 1.8mm nozzle, 800ml cup, 220V',
                      qty=2,  threshold=1,  zone='A', aisle='11', shelf='S3'),
            Equipment(sku='EQ-195', name='Rivet Gun',            category='Tools',
                      specifications='Pneumatic, 2.4–4.8mm rivets, 1/4 BSP inlet',
                      qty=4,  threshold=1,  zone='A', aisle='13', shelf='S1'),
            Equipment(sku='EQ-196', name='Caulking Gun',         category='Tools',
                      specifications='400ml sausage, pneumatic, 1/4 BSP, skeleton',
                      qty=5,  threshold=2,  zone='A', aisle='13', shelf='S2'),
            Equipment(sku='EQ-197', name='Label Maker',          category='Storage',
                      specifications='QWERTY keyboard, 12mm tape, 180 dpi, USB',
                      qty=3,  threshold=1,  zone='G', aisle='09', shelf='S1'),
            Equipment(sku='EQ-198', name='Document Safe',        category='Security',
                      specifications='30L, A4 files, 60-min fire rated, digital lock',
                      qty=1,  threshold=1,  zone='N', aisle='04', shelf='S1'),
            Equipment(sku='EQ-199', name='Portable Lighting',    category='Electrical',
                      specifications='Rechargeable LED 20W, 1800 lm, 8h, magnet base',
                      qty=6,  threshold=2,  zone='E', aisle='10', shelf='S2'),
            Equipment(sku='EQ-200', name='Tool Cabinet',         category='Storage',
                      specifications='7-drawer, 600mm wide, 950kg load, lockable',
                      qty=2,  threshold=1,  zone='G', aisle='10', shelf='S1'),
        ]:
            db.session.add(item)
        db.session.commit()


# ── Auth routes ───────────────────────────────────────────────────────────────


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid username or password.')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Dashboard (search + inventory table) ──────────────────────────────────────

@app.route('/')
@login_required
def home():
    q = request.args.get('q', '').strip()
    query = Equipment.query
    if q:
        like = f'%{q}%'
        query = query.filter(or_(
            Equipment.name.ilike(like),
            Equipment.sku.ilike(like),
            Equipment.category.ilike(like),
            Equipment.specifications.ilike(like),
        ))
    inventory      = query.order_by(Equipment.name).all()
    history        = Transaction.query.order_by(Transaction.timestamp.desc()).limit(50).all()
    unacked_alerts = AlertLog.query.filter_by(acknowledged=False).count()
    return render_template('index.html', inventory=inventory, history=history,
                           search_query=q, unacked_alerts=unacked_alerts)


# ── Inventory management ──────────────────────────────────────────────────────

@app.route('/add', methods=['POST'])
@login_required
@role_required('clerk', 'manager', 'admin')
def add_item():
    if Equipment.query.filter_by(sku=request.form.get('sku')).first():
        flash(f'SKU "{request.form.get("sku")}" already exists.')
        return redirect(url_for('home'))
    item = Equipment(
        sku            = request.form.get('sku').upper(),
        name           = request.form.get('item_name'),
        category       = request.form.get('category'),
        specifications = request.form.get('specifications'),
        qty            = int(request.form.get('item_qty')),
        threshold      = int(request.form.get('threshold') or 5),
        zone           = request.form.get('zone').upper(),
        aisle          = request.form.get('aisle'),
        shelf          = request.form.get('shelf').upper(),
    )
    db.session.add(item)
    db.session.commit()
    flash(f'Item "{item.name}" (SKU: {item.sku}) added to inventory.')
    return redirect(url_for('home'))


@app.route('/checkout/<int:item_id>', methods=['POST'])
@login_required
def checkout_item(item_id):
    item     = Equipment.query.get_or_404(item_id)
    take_qty = int(request.form.get('take_qty'))
    person   = request.form.get('person')

    if take_qty > item.qty:
        flash(f'Cannot checkout {take_qty} — only {item.qty} in stock.')
        return redirect(url_for('home'))

    item.qty -= take_qty
    db.session.add(Transaction(item_name=item.name, action=f'Out ({take_qty})', person=person))

    if item.qty <= item.threshold:
        db.session.add(AlertLog(
            item_id      = item.id,
            item_name    = item.name,
            qty_at_alert = item.qty,
            threshold    = item.threshold,
        ))

    db.session.commit()
    return redirect(url_for('home'))


@app.route('/restock/<int:item_id>', methods=['POST'])
@login_required
@role_required('clerk', 'manager', 'admin')
def restock_item(item_id):
    item     = Equipment.query.get_or_404(item_id)
    add_qty  = int(request.form.get('add_qty'))
    person   = request.form.get('person')

    if add_qty < 1:
        flash('Restock quantity must be at least 1.')
        return redirect(url_for('home'))

    item.qty += add_qty
    db.session.add(Transaction(item_name=item.name, action=f'In ({add_qty})', person=person))
    db.session.commit()
    flash(f'Restocked {add_qty} unit(s) of "{item.name}".')
    return redirect(url_for('home'))


# ── Alert management (manager / admin) ────────────────────────────────────────

@app.route('/alerts')
@login_required
@role_required('manager', 'admin')
def alerts():
    all_alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).all()
    return render_template('alerts.html', alerts=all_alerts,
                           unacked_alerts=AlertLog.query.filter_by(acknowledged=False).count())


@app.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
@role_required('manager', 'admin')
def acknowledge_alert(alert_id):
    alert                 = AlertLog.query.get_or_404(alert_id)
    alert.acknowledged    = True
    alert.acknowledged_by = current_user.username
    alert.acknowledged_at = datetime.utcnow()
    db.session.commit()
    flash(f'Alert for "{alert.item_name}" acknowledged.')
    return redirect(url_for('alerts'))


# ── Reports (manager / admin) ─────────────────────────────────────────────────

@app.route('/export/csv')
@login_required
@role_required('manager', 'admin')
def export_csv():
    inventory = Equipment.query.order_by(Equipment.name).all()

    def generate():
        yield 'SKU,Item Name,Category,Specifications,Quantity,Threshold,Zone,Aisle,Shelf,Status\n'
        for item in inventory:
            specs = (item.specifications or '').replace(',', ';')
            yield (f'{item.sku},{item.name},{item.category},{specs},'
                   f'{item.qty},{item.threshold},{item.zone},{item.aisle},{item.shelf},{item.status}\n')

    return Response(generate(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=inventory_report.csv'})


@app.route('/export/pdf')
@login_required
@role_required('manager', 'admin')
def export_pdf():
    if not REPORTLAB:
        flash('PDF export unavailable. Run: pip install reportlab')
        return redirect(url_for('home'))

    inventory = Equipment.query.order_by(Equipment.name).all()
    buf       = io.BytesIO()
    doc       = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                  leftMargin=1.5*cm, rightMargin=1.5*cm,
                                  topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = [
        Paragraph('Integrated Inventory Locator and Management System', styles['Title']),
        Paragraph(f'Stock Status Report — {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
                  styles['Normal']),
        Spacer(1, 0.5*cm),
    ]

    rows = [['SKU', 'Item Name', 'Category', 'Specifications', 'Qty', 'Threshold', 'Location', 'Status']]
    for item in inventory:
        rows.append([item.sku, item.name, item.category,
                     item.specifications or '—',
                     str(item.qty), str(item.threshold),
                     item.location, item.status])

    t = Table(rows, colWidths=[2.5*cm, 4*cm, 3*cm, 6*cm, 1.5*cm, 2*cm, 3.5*cm, 2.5*cm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0),  rl_colors.HexColor('#1e3a5f')),
        ('TEXTCOLOR',  (0, 0), (-1, 0),  rl_colors.white),
        ('FONTNAME',   (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 8),
        ('GRID',       (0, 0), (-1, -1), 0.5, rl_colors.HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor('#f8fafc')]),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING',    (0, 0), (-1, -1), 4),
    ]))

    for i, item in enumerate(inventory, start=1):
        if item.status == 'Out of Stock':
            t.setStyle(TableStyle([
                ('BACKGROUND', (-1, i), (-1, i), rl_colors.HexColor('#fee2e2')),
                ('TEXTCOLOR',  (-1, i), (-1, i), rl_colors.HexColor('#dc2626')),
            ]))
        elif item.status == 'Low':
            t.setStyle(TableStyle([
                ('BACKGROUND', (-1, i), (-1, i), rl_colors.HexColor('#fef9c3')),
                ('TEXTCOLOR',  (-1, i), (-1, i), rl_colors.HexColor('#92400e')),
            ]))

    story.append(t)
    doc.build(story)
    buf.seek(0)
    return Response(buf.read(), mimetype='application/pdf',
                    headers={'Content-Disposition': 'attachment;filename=inventory_report.pdf'})


# ── User management (admin only) ──────────────────────────────────────────────

@app.route('/users')
@login_required
@role_required('admin')
def manage_users():
    users          = User.query.order_by(User.role, User.username).all()
    unacked_alerts = AlertLog.query.filter_by(acknowledged=False).count()
    return render_template('users.html', users=users, unacked_alerts=unacked_alerts)


@app.route('/users/add', methods=['POST'])
@login_required
@role_required('admin')
def add_user():
    username = request.form.get('username').strip()
    if User.query.filter_by(username=username).first():
        flash(f'Username "{username}" already exists.')
    else:
        u = User(username=username, role=request.form.get('role'))
        u.set_password(request.form.get('password'))
        db.session.add(u)
        db.session.commit()
        flash(f'User "{username}" created.')
    return redirect(url_for('manage_users'))


@app.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.')
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f'User "{user.username}" deleted.')
    return redirect(url_for('manage_users'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
