from flask import Flask, render_template, request, redirect, session, url_for, jsonify, g, flash, Response
import os
import time
import json
import uuid
import csv
import io
import sqlite3
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from model.analyzer import analyze_leaf
from database.create_db import ensure_columns, init_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'crop_disease_secret_key_123_leafdoc_app')

DATABASE = os.path.join(os.path.dirname(__file__), 'database', 'crop_disease.db')
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# In-memory weather cache: { region_or_coord: (timestamp, weather_dict) }
WEATHER_CACHE = {}
WEATHER_CACHE_TTL = 900  # 15 minutes in seconds

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def is_logged_in():
    return 'farmer_id' in session

def is_admin():
    return is_logged_in() and session.get('is_admin') == 1

def compute_disease_risk(temp, humidity, rain):
    risk = "Low"
    risk_msg = "Conditions look favorable for healthy crop growth."
    if humidity and humidity > 75 and temp and temp > 20:
        risk = "High"
        risk_msg = "High humidity & warm temperature — elevated risk of fungal blight. Monitor crops closely."
    elif rain and rain > 2:
        risk = "Moderate"
        risk_msg = "Recent rainfall detected — watch for waterlogging and fungal disease risk."
    elif humidity and humidity > 80:
        risk = "Moderate"
        risk_msg = "Elevated humidity detected — ensure good canopy airflow to prevent mildew."
    return risk, risk_msg

def fallback_weather(region="Local Farm", lat=12.9716, lon=77.5946):
    import datetime
    month = datetime.datetime.now().month
    if month in [6, 7, 8, 9]:
        temp = 26.5
        humidity = 82
        rain = 3.5
    elif month in [11, 12, 1, 2]:
        temp = 22.0
        humidity = 58
        rain = 0.0
    else:
        temp = 31.5
        humidity = 55
        rain = 0.2
    risk, risk_msg = compute_disease_risk(temp, humidity, rain)
    return {
        "temp": temp,
        "humidity": humidity,
        "rain": rain,
        "risk": risk,
        "risk_msg": risk_msg,
        "region": region,
        "lat": lat,
        "lon": lon,
        "is_simulated": True
    }

def get_weather(region):
    if not region:
        region = "Bengaluru"
    
    now = time.time()
    cache_key = f"region:{region.lower().strip()}"
    if cache_key in WEATHER_CACHE:
        cached_time, cached_data = WEATHER_CACHE[cache_key]
        if now - cached_time < WEATHER_CACHE_TTL:
            return cached_data

    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={region}&count=1"
        geo_res = requests.get(geo_url, timeout=3).json()
        if not geo_res.get('results'):
            fallback = fallback_weather(region=region)
            WEATHER_CACHE[cache_key] = (now, fallback)
            return fallback
        lat = geo_res['results'][0]['latitude']
        lon = geo_res['results'][0]['longitude']
        matched_name = geo_res['results'][0].get('name', region)

        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,precipitation,weather_code"
        weather_res = requests.get(weather_url, timeout=3).json()
        current = weather_res.get('current', {})

        temp = current.get('temperature_2m')
        humidity = current.get('relative_humidity_2m')
        rain = current.get('precipitation', 0)

        risk, risk_msg = compute_disease_risk(temp, humidity, rain)

        result = {
            "temp": temp,
            "humidity": humidity,
            "rain": rain,
            "risk": risk,
            "risk_msg": risk_msg,
            "region": matched_name,
            "lat": lat,
            "lon": lon
        }
        WEATHER_CACHE[cache_key] = (now, result)
        return result
    except Exception:
        fallback = fallback_weather(region=region)
        WEATHER_CACHE[cache_key] = (now, fallback)
        return fallback

# ---------- Geolocation & Hyper-Local Weather API ----------

@app.route('/api/weather/gps')
def api_weather_gps():
    lat = request.args.get('lat')
    lon = request.args.get('lon')

    if not lat or not lon:
        return jsonify({"success": False, "error": "Missing latitude/longitude"}), 400

    try:
        lat = float(lat)
        lon = float(lon)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid coordinates"}), 400

    cache_key = f"gps:{round(lat, 3)},{round(lon, 3)}"
    now = time.time()
    if cache_key in WEATHER_CACHE:
        cached_time, cached_data = WEATHER_CACHE[cache_key]
        if now - cached_time < WEATHER_CACHE_TTL:
            return jsonify({"success": True, "weather": cached_data, "cached": True})

    location_name = "Live Farm Location"
    try:
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,precipitation,weather_code"
        weather_res = requests.get(weather_url, timeout=3).json()
        current = weather_res.get('current', {})

        temp = current.get('temperature_2m')
        humidity = current.get('relative_humidity_2m')
        rain = current.get('precipitation', 0)

        risk, risk_msg = compute_disease_risk(temp, humidity, rain)

        # Attempt reverse geocode to get locality name
        try:
            rev_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10"
            rev_res = requests.get(rev_url, headers={'User-Agent': 'LeafDocCropApp/2.0'}, timeout=2).json()
            addr = rev_res.get('address', {})
            location_name = addr.get('village') or addr.get('town') or addr.get('city') or addr.get('county') or addr.get('state_district') or "Live Farm Location"
        except Exception:
            pass

        weather_data = {
            "temp": temp,
            "humidity": humidity,
            "rain": rain,
            "risk": risk,
            "risk_msg": risk_msg,
            "region": location_name,
            "lat": lat,
            "lon": lon
        }
        WEATHER_CACHE[cache_key] = (now, weather_data)

        # Save coordinates to current user's session & profile if logged in
        if is_logged_in():
            session['lat'] = lat
            session['lon'] = lon
            db = get_db()
            db.execute("UPDATE farmers SET latitude = ?, longitude = ? WHERE farmer_id = ?", (lat, lon, session['farmer_id']))
            db.commit()

        return jsonify({"success": True, "weather": weather_data})
    except Exception as e:
        fallback = fallback_weather(region=location_name, lat=lat, lon=lon)
        WEATHER_CACHE[cache_key] = (now, fallback)
        return jsonify({"success": True, "weather": fallback, "fallback": True})

# ---------- Authentication Routes ----------

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if is_logged_in():
        return redirect('/')

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        region = request.form.get('region', '').strip() or 'Bengaluru'
        password = request.form.get('password', '').strip()

        if not name or not phone or not password:
            return render_template('signup.html', error="Please fill in all required fields.")

        db = get_db()
        existing = db.execute("SELECT farmer_id FROM farmers WHERE phone = ?", (phone,)).fetchone()
        if existing:
            return render_template('signup.html', error="Phone number already registered. Please login.")

        hashed_password = generate_password_hash(password)
        cursor = db.execute(
            "INSERT INTO farmers (name, phone, region, password, is_admin) VALUES (?, ?, ?, ?, 0)",
            (name, phone, region, hashed_password)
        )
        db.commit()
        farmer_id = cursor.lastrowid

        session['farmer_id'] = farmer_id
        session['name'] = name
        session['phone'] = phone
        session['region'] = region
        session['is_admin'] = 0

        flash("Welcome to LeafDoc! Your account was created successfully.", "success")
        return redirect('/')

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect('/')

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        db = get_db()
        farmer = db.execute("SELECT farmer_id, name, phone, region, password, is_admin, latitude, longitude FROM farmers WHERE phone = ?", (phone,)).fetchone()

        if not farmer:
            return render_template('login.html', error="Invalid phone number or password.")

        stored_password = farmer['password']
        is_valid = False

        if stored_password.startswith(('pbkdf2:', 'scrypt:', 'argon2:')):
            is_valid = check_password_hash(stored_password, password)
        else:
            is_valid = (stored_password == password)
            if is_valid:
                db.execute("UPDATE farmers SET password = ? WHERE farmer_id = ?",
                           (generate_password_hash(password), farmer['farmer_id']))
                db.commit()

        if not is_valid:
            return render_template('login.html', error="Invalid phone number or password.")

        session['farmer_id'] = farmer['farmer_id']
        session['name'] = farmer['name']
        session['phone'] = farmer['phone']
        session['region'] = farmer['region']
        session['is_admin'] = farmer['is_admin']
        if farmer['latitude'] and farmer['longitude']:
            session['lat'] = farmer['latitude']
            session['lon'] = farmer['longitude']

        flash(f"Welcome back, {farmer['name']}!", "success")
        if farmer['is_admin'] == 1:
            return redirect('/admin')
        return redirect('/')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect('/login')

# ---------- Core App Routes ----------

@app.route('/')
def home():
    if not is_logged_in():
        return redirect('/login')

    import datetime
    month = datetime.datetime.now().month

    if month in [6, 7, 8, 9]:
        season_tip = "🌧️ Monsoon Season: High risk of fungal blight due to moisture. Ensure good drainage and avoid overhead watering."
    elif month in [11, 12, 1, 2]:
        season_tip = "❄️ Winter Season: Watch for powdery mildew in cooler, humid conditions. Ensure good air circulation."
    else:
        season_tip = "☀️ Summer Season: Water plants early morning to reduce heat stress and prevent leaf scorch."

    db = get_db()
    recent_scans = db.execute("""
        SELECT diseases.disease_name, detections.confidence, detections.detected_on,
               detections.crop_type, detections.severity
        FROM detections
        JOIN diseases ON detections.disease_id = diseases.disease_id
        WHERE detections.farmer_id = ?
        ORDER BY detections.detection_id DESC
        LIMIT 4
    """, (session.get('farmer_id'),)).fetchall()

    user_region = session.get('region', 'Bengaluru')
    weather = get_weather(user_region)

    return render_template('index.html', name=session.get('name'), season_tip=season_tip, recent_scans=recent_scans, weather=weather)

@app.route('/predict', methods=['POST'])
def predict():
    if not is_logged_in():
        return redirect('/login')

    if 'leaf_image' not in request.files:
        flash("No file part in upload.", "error")
        return redirect('/')

    file = request.files['leaf_image']
    crop_type = request.form.get('crop_type', 'Other').strip()
    plot_name = request.form.get('plot_name', '').strip() or f"{crop_type} Plot"
    lat_str = request.form.get('latitude', '')
    lon_str = request.form.get('longitude', '')

    lat = None
    lon = None
    if lat_str and lon_str:
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            pass

    if file.filename == '':
        flash("No file selected.", "error")
        return redirect('/')

    if not allowed_file(file.filename):
        flash("Invalid file format. Please upload JPG, PNG, or WEBP images.", "error")
        return redirect('/')

    safe_orig = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_orig}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    disease_name, confidence, symptoms, severity = analyze_leaf(filepath, crop_type=crop_type)

    if disease_name == "NOT_A_LEAF":
        return render_template('not_a_leaf.html', image_file=unique_name)

    db = get_db()

    disease_row = db.execute("""
        SELECT d.disease_id, d.disease_name, t.treatment_text, t.pesticide, t.dosage, t.precautions
        FROM diseases d
        LEFT JOIN treatments t ON d.disease_id = t.disease_id
        JOIN crops c ON d.crop_id = c.crop_id
        WHERE (d.disease_name = ? AND c.crop_name = ?)
           OR d.disease_name = ?
        LIMIT 1
    """, (disease_name, crop_type, disease_name)).fetchone()

    if not disease_row:
        disease_row = db.execute("""
            SELECT d.disease_id, d.disease_name, t.treatment_text, t.pesticide, t.dosage, t.precautions
            FROM diseases d
            LEFT JOIN treatments t ON d.disease_id = t.disease_id
            WHERE d.disease_name LIKE ?
            LIMIT 1
        """, (f"%{disease_name}%",)).fetchone()

    if disease_row:
        disease_id = disease_row['disease_id']
        disp_disease_name = disease_row['disease_name']
        treatment_text = disease_row['treatment_text'] or "Isolate affected crops and monitor foliage."
        pesticide = disease_row['pesticide'] or "None required"
        dosage = disease_row['dosage'] or "2-3 ml per Liter of water"
        precautions = disease_row['precautions'] or "Wear protective gloves and apply in cool morning hours."
    else:
        disease_id = 1
        disp_disease_name = disease_name
        treatment_text = "Prune infected leaves, avoid overhead watering, and ensure good airflow."
        pesticide = "Copper-based Fungicide"
        dosage = "2.0g per Liter of water"
        precautions = "Spray early morning. Avoid application during direct high sunlight."

    farmer_id = session.get('farmer_id')
    region = session.get('region', 'Unknown')
    farmer_name = session.get('name', 'Farmer')

    import datetime
    today_str = datetime.date.today().strftime('%Y-%m-%d')

    db.execute("""
        INSERT INTO detections (farmer_id, disease_id, region, confidence, detected_on, plot_name, crop_type, severity, image_file, latitude, longitude)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (farmer_id, disease_id, region, confidence, today_str, plot_name, crop_type, severity, unique_name, lat, lon))
    db.commit()

    return render_template('result.html',
                            disease_name=disp_disease_name,
                            confidence=confidence,
                            treatment_text=treatment_text,
                            pesticide=pesticide,
                            dosage=dosage,
                            precautions=precautions,
                            image_file=unique_name,
                            crop_type=crop_type,
                            severity=severity,
                            plot_name=plot_name,
                            symptoms=symptoms,
                            farmer_name=farmer_name,
                            region=region,
                            detected_on=today_str)

@app.route('/dashboard')
def dashboard():
    if not is_logged_in():
        return redirect('/login')

    db = get_db()

    disease_counts = db.execute("""
        SELECT diseases.disease_name, COUNT(*) as count
        FROM detections
        JOIN diseases ON detections.disease_id = diseases.disease_id
        GROUP BY diseases.disease_name
        ORDER BY count DESC
    """).fetchall()

    region_counts = db.execute("""
        SELECT region, COUNT(*) as count
        FROM detections
        GROUP BY region
        ORDER BY count DESC
    """).fetchall()

    city_coords = {
        "Bengaluru": [12.9716, 77.5946],
        "Mysuru": [12.2958, 76.6394],
        "Hubli": [15.3647, 75.1240],
        "Mangalore": [12.9141, 74.8560],
        "Delhi": [28.6139, 77.2090],
        "Mumbai": [19.0760, 72.8777],
        "Chennai": [13.0827, 80.2707],
        "Hyderabad": [17.3850, 78.4867],
        "Pune": [18.5204, 73.8567],
        "Kolkata": [22.5726, 88.3639],
        "HQ": [12.9716, 77.5946],
        "Unknown": [20.5937, 78.9629]
    }

    # Fetch individual GPS detection points if available
    gps_detections = db.execute("""
        SELECT detections.detection_id, diseases.disease_name, detections.region,
               detections.latitude, detections.longitude, detections.crop_type, detections.severity
        FROM detections
        JOIN diseases ON detections.disease_id = diseases.disease_id
        WHERE detections.latitude IS NOT NULL AND detections.longitude IS NOT NULL
    """).fetchall()

    map_points = []
    for row in region_counts:
        region_name = row['region']
        count = row['count']
        coords = city_coords.get(region_name, [20.5937, 78.9629])
        map_points.append({
            "name": region_name,
            "lat": coords[0],
            "lng": coords[1],
            "count": count,
            "type": "region_cluster"
        })

    # Append exact GPS points
    for row in gps_detections:
        map_points.append({
            "name": f"Scan #{row['detection_id']}: {row['disease_name']} ({row['crop_type']})",
            "lat": row['latitude'],
            "lng": row['longitude'],
            "count": 1,
            "severity": row['severity'],
            "type": "gps_scan"
        })

    time_counts = db.execute("""
        SELECT detected_on, COUNT(*) as count
        FROM detections
        GROUP BY detected_on
        ORDER BY detected_on ASC
    """).fetchall()

    total_scans_row = db.execute("SELECT COUNT(*) as count FROM detections").fetchone()
    total_scans = total_scans_row['count'] if total_scans_row else 0

    most_common_row = db.execute("""
        SELECT diseases.disease_name, COUNT(*) as count
        FROM detections
        JOIN diseases ON detections.disease_id = diseases.disease_id
        GROUP BY diseases.disease_name
        ORDER BY count DESC
        LIMIT 1
    """).fetchone()
    most_common_disease = most_common_row['disease_name'] if most_common_row else "N/A"

    healthy_count_row = db.execute("""
        SELECT COUNT(*) as count FROM detections
        JOIN diseases ON detections.disease_id = diseases.disease_id
        WHERE diseases.disease_name LIKE '%Healthy%'
    """).fetchone()
    healthy_count = healthy_count_row['count'] if healthy_count_row else 0
    healthy_percent = round((healthy_count / total_scans * 100), 1) if total_scans > 0 else 0

    return render_template('dashboard.html',
                            disease_labels=[row['disease_name'] for row in disease_counts],
                            disease_values=[row['count'] for row in disease_counts],
                            region_labels=[row['region'] for row in region_counts],
                            region_values=[row['count'] for row in region_counts],
                            time_labels=[row['detected_on'] for row in time_counts],
                            time_values=[row['count'] for row in time_counts],
                            total_scans=total_scans,
                            most_common_disease=most_common_disease,
                            healthy_percent=healthy_percent,
                            map_points=map_points)

@app.route('/history')
def history():
    if not is_logged_in():
        return redirect('/login')

    db = get_db()
    records = db.execute("""
        SELECT detections.detection_id, diseases.disease_name, detections.region,
               detections.confidence, detections.detected_on, detections.crop_type,
               detections.plot_name, detections.severity, detections.image_file
        FROM detections
        JOIN diseases ON detections.disease_id = diseases.disease_id
        ORDER BY detections.detection_id DESC
    """).fetchall()

    return render_template('history.html', records=records)

@app.route('/forum', methods=['GET', 'POST'])
def forum():
    if not is_logged_in():
        return redirect('/login')

    db = get_db()

    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        tag = request.form.get('tag', 'General').strip()
        if message:
            db.execute("""
                INSERT INTO forum_posts (farmer_id, farmer_name, message, tag, posted_on)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (session.get('farmer_id'), session.get('name'), message, tag))
            db.commit()
            flash("Your post was published to the forum!", "success")
            return redirect('/forum')

    posts = db.execute("""
        SELECT f.farmer_name, f.message, f.tag, f.posted_on, u.region
        FROM forum_posts f
        LEFT JOIN farmers u ON f.farmer_id = u.farmer_id
        ORDER BY f.post_id DESC
    """).fetchall()

    return render_template('forum.html', posts=posts)

# ---------- Shop & Multi-Item Shopping Cart Routes ----------

@app.route('/shop')
def shop():
    if not is_logged_in():
        return redirect('/login')

    db = get_db()
    category_filter = request.args.get('category')
    if category_filter:
        products = db.execute("SELECT * FROM products WHERE category = ? ORDER BY product_id DESC", (category_filter,)).fetchall()
    else:
        products = db.execute("SELECT * FROM products ORDER BY in_stock DESC, product_id DESC").fetchall()

    categories = db.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL").fetchall()

    user = db.execute("SELECT region, phone FROM farmers WHERE farmer_id = ?", (session.get('farmer_id'),)).fetchone()
    default_region = user['region'] if user else ''
    default_phone = user['phone'] if user else ''

    return render_template('shop.html', products=products, categories=[c['category'] for c in categories],
                           default_region=default_region, default_phone=default_phone,
                           current_category=category_filter)

@app.route('/shop/add-product', methods=['POST'])
def farmer_add_product():
    if not is_logged_in():
        return redirect('/login')

    name = request.form.get('product_name', '').strip()
    price = request.form.get('price')
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'Farmer Harvest').strip()
    emoji = request.form.get('emoji', '🌱').strip() or '🌱'

    if not name or not price:
        flash("Product name and price are required.", "error")
        return redirect('/shop')

    try:
        price = float(price)
    except ValueError:
        flash("Invalid price.", "error")
        return redirect('/shop')

    seller_id = session.get('farmer_id')
    seller_name = f"Farmer {session.get('name', 'Community')}"

    db = get_db()
    db.execute("""
        INSERT INTO products (product_name, price, description, emoji, category, seller_id, seller_name, in_stock, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
    """, (name, price, description, emoji, category, seller_id, seller_name))
    db.commit()

    flash(f"Your produce/seed listing '{name}' has been posted to the marketplace!", "success")
    return redirect('/shop')

@app.route('/cart/checkout', methods=['POST'])
def cart_checkout():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Please login to complete your order."}), 401

    data = request.get_json(silent=True)
    if not data:
        data = request.form

    items = data.get('items')
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []

    if not items or len(items) == 0:
        return jsonify({"success": False, "error": "Your cart is empty."}), 400

    address = data.get('address', '').strip() or f"Delivery to {session.get('region', 'Local Farm')}"
    payment_method = data.get('payment_method', 'Card').strip()
    contact_phone = data.get('phone', session.get('phone', '')).strip()
    notes = data.get('notes', '').strip()
    farmer_id = session.get('farmer_id')

    db = get_db()
    order_ids = []

    # Process all cart items
    for item in items:
        p_id = item.get('product_id')
        qty = int(item.get('quantity', 1))
        p_name = item.get('product_name', 'Item')
        p_price = float(item.get('price', 0))

        if p_id and qty > 0:
            cursor = db.execute("""
                INSERT INTO orders (farmer_id, product_id, quantity, ordered_on, delivery_address, payment_method, status, items_json, contact_phone, notes)
                VALUES (?, ?, ?, datetime('now'), ?, ?, 'Pending', ?, ?, ?)
            """, (farmer_id, p_id, qty, address, payment_method, json.dumps([item]), contact_phone, notes))
            order_ids.append(cursor.lastrowid)

    db.commit()

    return jsonify({
        "success": True,
        "message": f"Successfully placed order for {len(items)} items!",
        "order_ids": order_ids
    })

@app.route('/order', methods=['POST'])
def single_order():
    if not is_logged_in():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({"success": False, "error": "Not logged in"}), 401
        return redirect('/login')

    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))
    address = request.form.get('address', '').strip() or f"Delivery in {session.get('region', 'Local Farm')}"
    payment_method = request.form.get('payment_method', 'Card').strip()
    contact_phone = request.form.get('phone', session.get('phone', '')).strip()
    notes = request.form.get('notes', '').strip()

    if not product_id or quantity <= 0:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "error": "Invalid order parameters"}), 400
        flash("Invalid order details.", "error")
        return redirect('/shop')

    db = get_db()
    product = db.execute("SELECT product_name, price, emoji FROM products WHERE product_id = ?", (product_id,)).fetchone()
    items_json = json.dumps([{
        "product_id": product_id,
        "product_name": product['product_name'] if product else 'Item',
        "price": product['price'] if product else 0,
        "quantity": quantity,
        "emoji": product['emoji'] if product else '📦'
    }])

    cursor = db.execute("""
        INSERT INTO orders (farmer_id, product_id, quantity, ordered_on, delivery_address, payment_method, status, items_json, contact_phone, notes)
        VALUES (?, ?, ?, datetime('now'), ?, ?, 'Pending', ?, ?, ?)
    """, (session.get('farmer_id'), product_id, quantity, address, payment_method, items_json, contact_phone, notes))
    db.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({"success": True, "message": "Order placed successfully!", "order_id": cursor.lastrowid})

    flash("Order placed successfully!", "success")
    return redirect('/orders')

@app.route('/orders')
def orders():
    if not is_logged_in():
        return redirect('/login')

    db = get_db()
    my_orders = db.execute("""
        SELECT orders.order_id, products.product_name, products.emoji, orders.quantity,
               products.price, orders.ordered_on, orders.delivery_address,
               orders.payment_method, orders.status, orders.items_json, orders.contact_phone
        FROM orders
        LEFT JOIN products ON orders.product_id = products.product_id
        WHERE orders.farmer_id = ?
        ORDER BY orders.order_id DESC
    """, (session.get('farmer_id'),)).fetchall()

    return render_template('orders.html', orders=my_orders)

# ---------- Administrative Portal Routes ----------

@app.route('/admin')
def admin():
    if not is_admin():
        flash("Admin access required. Please login with administrator credentials.", "error")
        return redirect('/login')

    db = get_db()
    all_farmers = db.execute("SELECT farmer_id, name, phone, region, is_admin FROM farmers ORDER BY farmer_id DESC").fetchall()

    all_products = db.execute("SELECT * FROM products ORDER BY in_stock DESC, product_id DESC").fetchall()

    all_orders = db.execute("""
        SELECT orders.order_id, farmers.name, farmers.phone, products.product_name, products.emoji,
               orders.quantity, orders.ordered_on, orders.status, orders.delivery_address,
               orders.payment_method, (products.price * orders.quantity) as total_price
        FROM orders
        LEFT JOIN farmers ON orders.farmer_id = farmers.farmer_id
        LEFT JOIN products ON orders.product_id = products.product_id
        ORDER BY orders.order_id DESC
    """).fetchall()

    total_scans_row = db.execute("SELECT COUNT(*) as count FROM detections").fetchone()
    total_scans = total_scans_row['count'] if total_scans_row else 0

    revenue_result = db.execute("""
        SELECT SUM(products.price * orders.quantity) as total
        FROM orders
        JOIN products ON orders.product_id = products.product_id
    """).fetchone()
    total_revenue = revenue_result['total'] if revenue_result and revenue_result['total'] else 0

    return render_template('admin.html',
                           farmers=all_farmers,
                           orders=all_orders,
                           products=all_products,
                           total_scans=total_scans,
                           total_revenue=total_revenue)

@app.route('/admin/product/add', methods=['POST'])
def admin_product_add():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    name = request.form.get('product_name', '').strip()
    price = request.form.get('price')
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'Supplies').strip()
    emoji = request.form.get('emoji', '📦').strip() or '📦'
    seller_name = request.form.get('seller_name', 'LeafDoc Store').strip() or 'LeafDoc Store'

    if not name or not price:
        flash("Product name and price are required.", "error")
        return redirect('/admin')

    try:
        price = float(price)
    except ValueError:
        flash("Invalid price.", "error")
        return redirect('/admin')

    db = get_db()
    db.execute("""
        INSERT INTO products (product_name, price, description, emoji, category, seller_id, seller_name, in_stock, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
    """, (name, price, description, emoji, category, session.get('farmer_id', 1), seller_name))
    db.commit()

    flash(f"Product '{name}' added to store catalog successfully!", "success")
    return redirect('/admin')

@app.route('/admin/product/edit', methods=['POST'])
def admin_product_edit():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    product_id = request.form.get('product_id')
    name = request.form.get('product_name', '').strip()
    price = request.form.get('price')
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'Supplies').strip()
    emoji = request.form.get('emoji', '📦').strip()
    in_stock = 1 if request.form.get('in_stock') == '1' else 0

    if not product_id or not name or not price:
        flash("Required fields missing.", "error")
        return redirect('/admin')

    db = get_db()
    db.execute("""
        UPDATE products
        SET product_name = ?, price = ?, description = ?, emoji = ?, category = ?, in_stock = ?
        WHERE product_id = ?
    """, (name, float(price), description, emoji, category, in_stock, product_id))
    db.commit()

    flash(f"Product #{product_id} updated successfully.", "success")
    return redirect('/admin')

@app.route('/admin/product/delete/<int:product_id>', methods=['POST'])
def admin_product_delete(product_id):
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    db = get_db()
    db.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
    db.commit()

    flash(f"Product #{product_id} removed from catalog.", "info")
    return redirect('/admin')

@app.route('/admin/order/update', methods=['POST'])
def update_order_status():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    order_id = request.form.get('order_id')
    new_status = request.form.get('status', 'Pending')

    db = get_db()
    db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (new_status, order_id))
    db.commit()

    flash(f"Order #{order_id} status updated to '{new_status}'.", "success")
    return redirect('/admin')

@app.route('/admin/order/delete/<int:order_id>', methods=['POST'])
def admin_order_delete(order_id):
    if not is_admin():
        
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    db = get_db()
    db.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
    db.commit()

    flash(f"Order #{order_id} has been deleted.", "info")
    return redirect('/admin')

@app.route('/admin/farmer/toggle-admin/<int:farmer_id>', methods=['POST'])
def admin_toggle_role(farmer_id):
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    db = get_db()
    farmer = db.execute("SELECT is_admin FROM farmers WHERE farmer_id = ?", (farmer_id,)).fetchone()
    if farmer:
        new_role = 0 if farmer['is_admin'] == 1 else 1
        db.execute("UPDATE farmers SET is_admin = ? WHERE farmer_id = ?", (new_role, farmer_id))
        db.commit()
        flash(f"Farmer #{farmer_id} admin privileges {'granted' if new_role==1 else 'revoked'}.", "success")

    return redirect('/admin')

@app.route('/admin/farmer/delete/<int:farmer_id>', methods=['POST'])
def admin_farmer_delete(farmer_id):
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    if farmer_id == session.get('farmer_id'):
        flash("You cannot delete your own active administrator account.", "error")
        return redirect('/admin')

    db = get_db()
    db.execute("DELETE FROM farmers WHERE farmer_id = ?", (farmer_id,))
    db.commit()

    flash(f"Farmer account #{farmer_id} deleted.", "info")
    return redirect('/admin')

@app.route('/admin/export/scans')
def export_scans():
    if not is_admin():
        return redirect('/login')

    db = get_db()
    scans = db.execute("""
        SELECT d.detection_id, f.name, d.crop_type, dis.disease_name, d.confidence,
               d.severity, d.region, d.detected_on
        FROM detections d
        LEFT JOIN farmers f ON d.farmer_id = f.farmer_id
        LEFT JOIN diseases dis ON d.disease_id = dis.disease_id
        ORDER BY d.detection_id DESC
    """).fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Scan ID', 'Farmer Name', 'Crop Type', 'Disease Name', 'Confidence (%)', 'Severity', 'Region', 'Date'])
    for s in scans:
        cw.writerow([s['detection_id'], s['name'], s['crop_type'], s['disease_name'], s['confidence'], s['severity'], s['region'], s['detected_on']])

    output = Response(si.getvalue(), mimetype='text/csv')
    output.headers["Content-Disposition"] = "attachment; filename=leafdoc_scans_report.csv"
    return output

@app.route('/admin/export/orders')
def export_orders():
    if not is_admin():
        return redirect('/login')

    db = get_db()
    orders = db.execute("""
        SELECT o.order_id, f.name, f.phone, p.product_name, o.quantity,
               p.price, (p.price * o.quantity) as total, o.status, o.delivery_address, o.ordered_on
        FROM orders o
        LEFT JOIN farmers f ON o.farmer_id = f.farmer_id
        LEFT JOIN products p ON o.product_id = p.product_id
        ORDER BY o.order_id DESC
    """).fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Order ID', 'Farmer Name', 'Phone', 'Product Name', 'Quantity', 'Price (INR)', 'Total (INR)', 'Status', 'Address', 'Ordered Date'])
    for o in orders:
        cw.writerow([o['order_id'], o['name'], o['phone'], o['product_name'], o['quantity'], o['price'], o['total'], o['status'], o['delivery_address'], o['ordered_on']])

    output = Response(si.getvalue(), mimetype='text/csv')
    output.headers["Content-Disposition"] = "attachment; filename=leafdoc_orders_report.csv"
    return output

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not is_logged_in():
        return redirect('/login')

    db = get_db()
    message = None

    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        new_region = request.form.get('region', '').strip()
        new_password = request.form.get('password', '').strip()

        if new_name and new_region:
            if new_password:
                hashed = generate_password_hash(new_password)
                db.execute("UPDATE farmers SET name=?, region=?, password=? WHERE farmer_id=?",
                           (new_name, new_region, hashed, session.get('farmer_id')))
            else:
                db.execute("UPDATE farmers SET name=?, region=? WHERE farmer_id=?",
                           (new_name, new_region, session.get('farmer_id')))
            db.commit()

            session['name'] = new_name
            session['region'] = new_region
            message = "Profile updated successfully!"

    farmer = db.execute("SELECT name, phone, region, latitude, longitude FROM farmers WHERE farmer_id = ?", (session.get('farmer_id'),)).fetchone()

    return render_template('profile.html', farmer=farmer, message=message)

@app.route('/planting-guide')
def planting_guide():
    if not is_logged_in():
        return redirect('/login')
    return render_template('planting_guide.html')

# Auto-check DB schema on startup
with app.app_context():
    try:
        conn = get_db()
        ensure_columns(conn)
    except Exception as e:
        print("Schema check error:", e)

if __name__ == '__main__':
    print("LeafDoc Crop Disease Advisory server starting on http://127.0.0.1:5000")
    app.run(debug=True, use_reloader=False, port=5000)