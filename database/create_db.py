import sqlite3
from werkzeug.security import generate_password_hash

def ensure_columns(conn):
    cursor = conn.cursor()
    
    def add_column_if_missing(table, col_name, col_type):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [info[1] for info in cursor.fetchall()]
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")

    # Treatments table columns
    add_column_if_missing('treatments', 'dosage', "TEXT DEFAULT '2-3 ml per Liter of water'")
    add_column_if_missing('treatments', 'precautions', "TEXT DEFAULT 'Wear protective gloves and spray early morning.'")
    
    # Orders table columns
    add_column_if_missing('orders', 'delivery_address', "TEXT DEFAULT 'Not provided'")
    add_column_if_missing('orders', 'payment_method', "TEXT DEFAULT 'Card'")
    add_column_if_missing('orders', 'status', "TEXT DEFAULT 'Pending'")
    add_column_if_missing('orders', 'items_json', "TEXT DEFAULT ''")
    add_column_if_missing('orders', 'contact_phone', "TEXT DEFAULT ''")
    add_column_if_missing('orders', 'notes', "TEXT DEFAULT ''")

    # Products table columns
    add_column_if_missing('products', 'category', "TEXT DEFAULT 'Supplies'")
    add_column_if_missing('products', 'seller_id', "INTEGER DEFAULT 1")
    add_column_if_missing('products', 'seller_name', "TEXT DEFAULT 'LeafDoc Verified'")
    add_column_if_missing('products', 'in_stock', "INTEGER DEFAULT 1")
    add_column_if_missing('products', 'created_at', "TEXT DEFAULT ''")

    # Forum posts table columns
    add_column_if_missing('forum_posts', 'tag', "TEXT DEFAULT 'General'")

    # Detections table columns
    add_column_if_missing('detections', 'crop_type', "TEXT DEFAULT 'Other'")
    add_column_if_missing('detections', 'severity', "TEXT DEFAULT 'Moderate'")
    add_column_if_missing('detections', 'image_file', "TEXT")
    add_column_if_missing('detections', 'latitude', "REAL")
    add_column_if_missing('detections', 'longitude', "REAL")

    # Farmers table columns
    add_column_if_missing('farmers', 'latitude', "REAL")
    add_column_if_missing('farmers', 'longitude', "REAL")

    conn.commit()

def init_db(db_path='database/crop_disease.db'):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    # ---------- Farmers Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS farmers (
        farmer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        region TEXT NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        latitude REAL,
        longitude REAL
    )
    ''')

    # ---------- Crops Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS crops (
        crop_id INTEGER PRIMARY KEY AUTOINCREMENT,
        crop_name TEXT UNIQUE NOT NULL
    )
    ''')

    # ---------- Diseases Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS diseases (
        disease_id INTEGER PRIMARY KEY AUTOINCREMENT,
        disease_name TEXT NOT NULL,
        crop_id INTEGER,
        FOREIGN KEY(crop_id) REFERENCES crops(crop_id)
    )
    ''')

    # ---------- Treatments Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS treatments (
        treatment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        disease_id INTEGER UNIQUE,
        treatment_text TEXT,
        pesticide TEXT,
        dosage TEXT DEFAULT '2-3 ml per Liter of water',
        precautions TEXT DEFAULT 'Wear protective gloves and spray early in the morning or late afternoon.',
        FOREIGN KEY(disease_id) REFERENCES diseases(disease_id)
    )
    ''')

    # ---------- Forum Posts Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS forum_posts (
        post_id INTEGER PRIMARY KEY AUTOINCREMENT,
        farmer_id INTEGER,
        farmer_name TEXT,
        message TEXT NOT NULL,
        tag TEXT DEFAULT 'General',
        posted_on TEXT,
        FOREIGN KEY(farmer_id) REFERENCES farmers(farmer_id)
    )
    ''')

    # ---------- Products Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        price REAL NOT NULL,
        description TEXT,
        emoji TEXT,
        category TEXT DEFAULT 'Supplies',
        seller_id INTEGER DEFAULT 1,
        seller_name TEXT DEFAULT 'LeafDoc Verified',
        in_stock INTEGER DEFAULT 1,
        created_at TEXT DEFAULT ''
    )
    ''')

    # ---------- Orders Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        farmer_id INTEGER,
        product_id INTEGER,
        quantity INTEGER NOT NULL,
        ordered_on TEXT,
        delivery_address TEXT DEFAULT 'Not provided',
        payment_method TEXT DEFAULT 'Card',
        status TEXT DEFAULT 'Pending',
        items_json TEXT DEFAULT '',
        contact_phone TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        FOREIGN KEY(farmer_id) REFERENCES farmers(farmer_id),
        FOREIGN KEY(product_id) REFERENCES products(product_id)
    )
    ''')

    # ---------- Detections Table ----------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS detections (
        detection_id INTEGER PRIMARY KEY AUTOINCREMENT,
        farmer_id INTEGER,
        disease_id INTEGER,
        region TEXT,
        confidence REAL,
        detected_on DATE,
        plot_name TEXT,
        crop_type TEXT DEFAULT 'Other',
        severity TEXT DEFAULT 'Moderate',
        image_file TEXT,
        latitude REAL,
        longitude REAL,
        FOREIGN KEY(farmer_id) REFERENCES farmers(farmer_id),
        FOREIGN KEY(disease_id) REFERENCES diseases(disease_id)
    )
    ''')

    # Run column migration for existing database
    ensure_columns(conn)

    # ---------- Seed Crops ----------
    crops_data = [
        'Tomato', 'Potato', 'Wheat', 'Rice', 'Chili',
        'Cotton', 'Sugarcane', 'Maize', 'Other'
    ]
    for crop in crops_data:
        cursor.execute("INSERT OR IGNORE INTO crops (crop_name) VALUES (?)", (crop,))

    conn.commit()

    # Build crop mapping
    cursor.execute("SELECT crop_name, crop_id FROM crops")
    crop_map = dict(cursor.fetchall())

    # ---------- Seed Diseases & Treatments ----------
    disease_treatments = [
        # Tomato
        ('Tomato Leaf Blight', crop_map['Tomato'],
         'Remove and destroy infected leaves. Ensure wide plant spacing and avoid overhead watering.',
         'Copper-based Fungicide (Blitox 50)', '2.5g per Liter of water',
         'Spray during early morning. Do not harvest within 7 days of application.'),

        ('Bacterial Leaf Spot', crop_map['Tomato'],
         'Prune affected lower leaves, sterilize garden shears, and avoid wetting foliage during irrigation.',
         'Copper Hydroxide Spray (Kocide)', '2.0g per Liter of water',
         'Avoid spraying during extreme mid-day heat. Use clean non-chlorinated water.'),

        ('Tomato Yellow Leaf Curl', crop_map['Tomato'],
         'Eradicate silverleaf whiteflies which transmit the virus. Use yellow sticky traps and reflective mulch.',
         'Neem Oil 10000 PPM or Imidacloprid', '1.5ml per Liter of water',
         'Spray under-surfaces of leaves where whiteflies congregate.'),

        ('Healthy Leaf', crop_map['Tomato'],
         'No treatment required. Crop is in prime condition. Continue standard watering and nutrient schedule.',
         'None required', 'N/A',
         'Maintain balanced NPK fertilization and monitor weekly.'),

        # Potato
        ('Potato Late Blight', crop_map['Potato'],
         'Improve field drainage, mound soil around tuber bases, and remove diseased vines immediately.',
         'Mancozeb 75% WP (Dithane M-45)', '2.5g per Liter of water',
         'Apply preventively before prolonged rainfall spells.'),

        ('Potato Early Blight', crop_map['Potato'],
         'Maintain optimal nitrogen levels and rotate crops with non-solanaceous plants yearly.',
         'Chlorothalonil 75% WP (Kavach)', '2.0g per Liter of water',
         'Ensure thorough coverage on both upper and lower foliage surfaces.'),

        ('Healthy Leaf', crop_map['Potato'],
         'Foliage is vigorous and healthy. Ensure consistent soil moisture to prevent hollow heart.',
         'None required', 'N/A',
         'Ensure good mounding to shield developing tubers from sunlight.'),

        # Wheat
        ('Wheat Leaf Rust', crop_map['Wheat'],
         'Apply systemic triazole fungicide at flag leaf emergence and plant rust-resistant cultivars.',
         'Propiconazole 25% EC (Tilt)', '1.0ml per Liter of water',
         'Wear respirator during application. Observe 30-day pre-harvest interval.'),

        ('Wheat Powdery Mildew', crop_map['Wheat'],
         'Improve air penetration across dense canopies. Avoid excess nitrogen fertilization.',
         'Wettable Sulfur 80% WDG (Sulfex)', '3.0g per Liter of water',
         'Avoid applying when temperatures exceed 32°C to prevent sulfur burn.'),

        ('Healthy Leaf', crop_map['Wheat'],
         'Wheat canopy is disease-free. Maintain balanced irrigation during flowering and grain fill.',
         'None required', 'N/A',
         'Monitor soil moisture during the critical crown root initiation phase.'),

        # Rice
        ('Rice Blast', crop_map['Rice'],
         'Avoid excess urea application. Drain water temporarily if blast symptoms appear.',
         'Tricyclazole 75% WP (Beam)', '0.6g per Liter of water',
         'Apply at early tillering and panicle emergence for maximum protection.'),

        ('Bacterial Leaf Blight', crop_map['Rice'],
         'Ensure good drainage, avoid clipping seedling tips before transplanting, and apply potash.',
         'Streptocycline + Copper Oxychloride', '0.5g Streptocycline + 2.5g Copper per 10L',
         'Apply immediately at first sign of water-soaked lesions on leaf margins.'),

        ('Rice Brown Spot', crop_map['Rice'],
         'Improve soil fertility with zinc and potassium. Use certified disease-free treated seeds.',
         'Carbendazim 50% WP (Bavistin)', '2.0g per Liter of water',
         'Treat seeds before sowing and spray canopy if brown circular spots expand.'),

        ('Healthy Leaf', crop_map['Rice'],
         'Paddy is vibrant and healthy. Maintain recommended water depth (2-5 cm) during vegetative stage.',
         'None required', 'N/A',
         'Monitor water salinity and maintain balanced nutrient inputs.'),

        # Chili
        ('Chili Anthracnose', crop_map['Chili'],
         'Remove necrotic stems and fruit. Mulch beds to prevent soil-borne spore splashing.',
         'Azoxystrobin 23% SC (Amistar)', '1.0ml per Liter of water',
         'Alternate with Mancozeb to prevent fungicide resistance.'),

        ('Chili Powdery Mildew', crop_map['Chili'],
         'Reduce humidity around plants, prune crowded branches, and spray wettable sulfur.',
         'Potassium Bicarbonate / Sulfex', '2.5g per Liter of water',
         'Spray early in the morning before sunlight becomes intense.'),

        ('Healthy Leaf', crop_map['Chili'],
         'Plant foliage is robust. Maintain well-drained loamy soil with steady drip irrigation.',
         'None required', 'N/A',
         'Stake tall plants to support heavy pepper yields.'),

        # Cotton
        ('Cotton Bacterial Blight', crop_map['Cotton'],
         'Use acid-delinted certified seeds. Clean machinery and pruning shears between fields.',
         'Copper Oxychloride 50% WP', '3.0g per Liter of water',
         'Spray when angular water-soaked leaf spots first appear.'),

        ('Cotton Leaf Curl', crop_map['Cotton'],
         'Uproot alternative weed hosts. Control whitefly populations with systemic insecticides.',
         'Neem Pesticide + Acetamiprid', '2.0ml Neem + 0.2g Acetamiprid per Liter',
         'Eradicate host weeds along field borders before planting.'),

        ('Healthy Leaf', crop_map['Cotton'],
         'Foliage shows excellent vigor. Maintain square and boll retention with micronutrient sprays.',
         'None required', 'N/A',
         'Scout weekly for bollworm and sucking pest infestations.'),

        # Sugarcane
        ('Sugarcane Red Rot', crop_map['Sugarcane'],
         'Use hot-water treated disease-free setts. Practice 3-year crop rotation and burn infected crop residue.',
         'Thiophanate Methyl 70% WP (Topsin-M)', '1.0g per Liter of water (Sett dip / spray)',
         'Do not use ratoon crops from infected fields.'),

        ('Sugarcane Rust', crop_map['Sugarcane'],
         'Strip lower dry infected leaves to enhance ventilation. Apply protective fungicides.',
         'Mancozeb 75% WP', '2.5g per Liter of water',
         'Spray when orange-brown pustules appear on lower leaf surfaces.'),

        ('Healthy Leaf', crop_map['Sugarcane'],
         'Canopy is thick and healthy. Continue regular earthing-up and furrow irrigation.',
         'None required', 'N/A',
         'Ensure adequate potassium application for high sucrose accumulation.'),

        # Maize
        ('Northern Corn Leaf Blight', crop_map['Maize'],
         'Deep-plow crop residue post harvest and rotate with legumes or soybean.',
         'Azoxystrobin + Difenoconazole (Amistar Top)', '1.0ml per Liter of water',
         'Spray when elongated cigar-shaped lesions appear on lower leaves.'),

        ('Maize Common Rust', crop_map['Maize'],
         'Plant resistant hybrid varieties and monitor fields in cool, humid weather.',
         'Pyraclostrobin or Mancozeb', '2.0g per Liter of water',
         'Target spray on upper leaves around silking stage.'),

        ('Healthy Leaf', crop_map['Maize'],
         'Maize foliage is lush and disease-free. Maintain nitrogen top-dressing at knee-high stage.',
         'None required', 'N/A',
         'Ensure uniform irrigation during silking and tasseling stages.'),

        # Other / Generic
        ('Leaf Blight', crop_map['Other'],
         'Remove infected leaves, ensure good airflow between plants, and avoid overhead watering.',
         'Copper-based Fungicide', '2.5g per Liter of water',
         'Apply during dry weather early in the day.'),

        ('Leaf Rust', crop_map['Other'],
         'Remove severely rusted foliage and avoid damp, stagnant air around crops.',
         'Sulfur-based Fungicide', '3.0g per Liter of water',
         'Spray thoroughly covering leaf undersides.'),

        ('Powdery Mildew', crop_map['Other'],
         'Improve sunlight penetration and reduce humidity around plant canopies.',
         'Potassium Bicarbonate Spray', '2.5g per Liter of water',
         'Reapply every 7-10 days until white powdery film clears.'),

        ('Bacterial Leaf Spot', crop_map['Other'],
         'Sterilize gardening tools, avoid handling wet plants, and prune infected shoots.',
         'Copper Hydroxide Spray', '2.0g per Liter of water',
         'Avoid spraying during high mid-day temperatures.'),

        ('Healthy Leaf', crop_map['Other'],
         'Leaf is completely healthy. Continue routine watering, sunlight, and compost care.',
         'None required', 'N/A',
         'Conduct weekly visual checks for early disease prevention.')
    ]

    for d_name, c_id, t_text, pest, dosage, precautions in disease_treatments:
        cursor.execute("SELECT disease_id FROM diseases WHERE disease_name = ? AND crop_id = ?", (d_name, c_id))
        existing = cursor.fetchone()
        if not existing:
            cursor.execute("INSERT INTO diseases (disease_name, crop_id) VALUES (?, ?)", (d_name, c_id))
            disease_id = cursor.lastrowid
        else:
            disease_id = existing[0]

        cursor.execute("SELECT treatment_id FROM treatments WHERE disease_id = ?", (disease_id,))
        treat_exists = cursor.fetchone()
        if not treat_exists:
            cursor.execute("""
                INSERT INTO treatments (disease_id, treatment_text, pesticide, dosage, precautions)
                VALUES (?, ?, ?, ?, ?)
            """, (disease_id, t_text, pest, dosage, precautions))
        else:
            cursor.execute("""
                UPDATE treatments SET treatment_text = ?, pesticide = ?, dosage = ?, precautions = ?
                WHERE disease_id = ?
            """, (t_text, pest, dosage, precautions, disease_id))

    # ---------- Seed Products (Safe Upsert) ----------
    products_data = [
        ('Tomato Sapling (10-pack)', 45.0, 'Healthy disease-resistant young tomato plants, ready to transplant.', '🍅', 'Plants & Seeds', 'LeafDoc Certified Nursery'),
        ('Potato Seed Tubers (1kg)', 60.0, 'Certified high-yield, blight-resistant potato seed tubers.', '🥔', 'Plants & Seeds', 'Agro Seed Bank'),
        ('Chili Sapling (10-pack)', 40.0, 'High-pungency, virus-resistant chili pepper plants.', '🌶️', 'Plants & Seeds', 'LeafDoc Certified Nursery'),
        ('Wheat Seeds (1kg)', 45.0, 'Premium rust-resistant HD-2967 wheat seed grain.', '🌾', 'Plants & Seeds', 'Farmer Suresh (Hubli)'),
        ('Neem Bio-Pesticide (500ml)', 150.0, 'Organic cold-pressed neem pesticide spray for all crops.', '🧴', 'Organic Treatments', 'Kisan Bio-Organic'),
        ('Copper Fungicide 50 WP (250g)', 180.0, 'Broad-spectrum copper fungicide against blight, rust, and spot.', '🧪', 'Chemical Treatments', 'LeafDoc Store'),
        ('Mancozeb 75% WP (500g)', 220.0, 'Trusted contact fungicide for early and late blight protection.', '💊', 'Chemical Treatments', 'LeafDoc Store'),
        ('Organic Vermicompost (5kg)', 120.0, 'Rich organic vermicompost for root health and soil aeration.', '🌱', 'Fertilizers', 'Farmer Ramesh (Bengaluru)')
    ]

    for p_name, price, desc, emoji, cat, seller in products_data:
        cursor.execute("SELECT product_id FROM products WHERE product_name = ?", (p_name,))
        p_row = cursor.fetchone()
        if not p_row:
            cursor.execute("INSERT INTO products (product_name, price, description, emoji, category, seller_name) VALUES (?, ?, ?, ?, ?, ?)",
                           (p_name, price, desc, emoji, cat, seller))
        else:
            cursor.execute("UPDATE products SET price = ?, description = ?, emoji = ?, category = ?, seller_name = ? WHERE product_name = ?",
                           (price, desc, emoji, cat, seller, p_name))

    # ---------- Seed Forum Posts (Safe Check) ----------
    cursor.execute("SELECT COUNT(*) FROM forum_posts")
    if cursor.fetchone()[0] == 0:
        posts_data = [
            (1, 'Ramesh Gowda', 'Tip: I spray neem oil early morning before sunrise — works much better than during the day when it evaporates fast!', 'Organic Farming', '-5 days'),
            (1, 'Priya Shetty', 'Does anyone know a good organic alternative to copper fungicide? My tomato plants have mild blight starting.', 'Disease Help', '-4 days'),
            (1, 'Suresh Naik', 'Rotating crops every season really helped reduce disease in my field. Wheat one season, legumes the next — big difference!', 'Crop Rotation', '-3 days'),
            (1, 'Lakshmi Devi', 'Watering at the base instead of overhead cut my powdery mildew problem almost completely. Highly recommend trying it.', 'Watering Tips', '-2 days'),
            (1, 'Manjunath R', 'Used the LeafDoc scanner on my potato crop today — caught early blight before it spread. The dosage guide is super handy!', 'Scanner Feedback', '-1 days'),
            (1, 'Anitha Kumari', 'Reminder for everyone: clean your shears and tools between plants! Bacterial spot spreads easily through contaminated equipment.', 'Prevention', 'now')
        ]
        for f_id, f_name, msg, tag, offset in posts_data:
            time_str = "datetime('now')" if offset == 'now' else f"datetime('now', '{offset}')"
            cursor.execute(f"INSERT INTO forum_posts (farmer_id, farmer_name, message, tag, posted_on) VALUES (?, ?, ?, ?, {time_str})",
                           (f_id, f_name, msg, tag))

    # ---------- Seed Default Admin Account (Hashed Password) ----------
    admin_phone = '9999999999'
    hashed_pwd = generate_password_hash('admin123')
    cursor.execute("SELECT farmer_id FROM farmers WHERE phone = ?", (admin_phone,))
    admin_exists = cursor.fetchone()
    if not admin_exists:
        cursor.execute("INSERT INTO farmers (name, phone, region, password, is_admin) VALUES (?, ?, ?, ?, 1)",
                       ('Admin', admin_phone, 'HQ', hashed_pwd))
    else:
        cursor.execute("UPDATE farmers SET password = ?, is_admin = 1 WHERE phone = ?", (hashed_pwd, admin_phone))

    conn.commit()
    conn.close()
    print("Database initialized and upgraded successfully with geolocation & cart schema!")

if __name__ == '__main__':
    init_db()