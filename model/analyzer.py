from PIL import Image
import numpy as np

def analyze_leaf(image_path, crop_type='Other'):
    """
    Analyzes an uploaded leaf image using HSV color space segmentation.
    Returns:
        disease_name (str): The identified disease or 'NOT_A_LEAF' / 'Healthy Leaf'
        confidence (float): Confidence percentage (0-100)
        symptoms (dict): Percentage breakdown of visual symptoms
        severity (str): 'Mild', 'Moderate', or 'Severe'
    """
    img = Image.open(image_path).convert('RGB')
    img = img.resize((200, 200))
    
    pixels = np.array(img) / 255.0
    
    r = pixels[:, :, 0]
    g = pixels[:, :, 1]
    b = pixels[:, :, 2]
    
    maxc = np.max(pixels, axis=2)
    minc = np.min(pixels, axis=2)
    diff = maxc - minc
    saturation = diff / (maxc + 0.0001)
    
    # Identify background (very bright white/light grey, or very dark borders with low saturation)
    background_mask = ((maxc > 0.88) & (saturation < 0.18)) | ((maxc < 0.10) & (saturation < 0.15))
    leaf_mask = ~background_mask
    
    total_leaf_pixels = np.sum(leaf_mask)
    if total_leaf_pixels == 0:
        total_leaf_pixels = 1
        leaf_mask = np.ones_like(maxc, dtype=bool)

    # Validate that image contains plant foliage colors
    green_or_yellowish = np.sum((g > r * 0.75) & (g > 0.12)) / (pixels.shape[0] * pixels.shape[1])
    if green_or_yellowish < 0.04 and (np.sum(leaf_mask) / (pixels.shape[0] * pixels.shape[1])) < 0.25:
        return "NOT_A_LEAF", 0.0, {}, "None"
        
    diff_safe = diff.copy()
    diff_safe[diff_safe == 0] = 0.0001
    
    hue = np.zeros_like(maxc)
    r_is_max = (maxc == r)
    g_is_max = (maxc == g)
    b_is_max = (maxc == b)
    
    hue[r_is_max] = (60 * ((g[r_is_max] - b[r_is_max]) / diff_safe[r_is_max]) + 360) % 360
    hue[g_is_max] = (60 * ((b[g_is_max] - r[g_is_max]) / diff_safe[g_is_max]) + 120) % 360
    hue[b_is_max] = (60 * ((r[b_is_max] - g[b_is_max]) / diff_safe[b_is_max]) + 240) % 360
    
    # 1. GREEN = Healthy foliage (Hue 65-170)
    green_mask = (hue >= 65) & (hue <= 170) & leaf_mask & (saturation > 0.10)
    green_percent = float(np.sum(green_mask) / total_leaf_pixels * 100)
    
    # 2. YELLOW = Chlorosis / Rust / Yellow leaf curl (Hue 40-65)
    yellow_mask = (hue >= 40) & (hue < 65) & leaf_mask & (saturation > 0.15) & (maxc > 0.35)
    yellow_percent = float(np.sum(yellow_mask) / total_leaf_pixels * 100)
    
    # 3. BROWN / ORANGE = Necrotic lesions / Blight / Anthracnose (Hue 15-40)
    brown_mask = (hue >= 15) & (hue < 40) & leaf_mask & (saturation > 0.14) & (maxc >= 0.25)
    brown_percent = float(np.sum(brown_mask) / total_leaf_pixels * 100)
    
    # 4. RED / PURPLE = Bacterial spots / Red rot (Hue 0-15 or >340)
    red_mask = (((hue >= 0) & (hue < 15)) | (hue > 340)) & leaf_mask & (saturation > 0.18) & (maxc > 0.20)
    red_percent = float(np.sum(red_mask) / total_leaf_pixels * 100)
    
    # 5. WHITE / PALE = Powdery Mildew
    white_patch_mask = (maxc > 0.58) & (saturation < 0.14) & leaf_mask & (~green_mask)
    white_percent = float(np.sum(white_patch_mask) / total_leaf_pixels * 100)
    
    # 6. DARK / BLACK = Severe Late Blight / Sooty Mold
    dark_mask = (leaf_mask & ~green_mask) & (maxc < 0.26)
    dark_percent = float(np.sum(dark_mask) / total_leaf_pixels * 100)
    
    blight_total = brown_percent + dark_percent
    total_disease_signal = yellow_percent + blight_total + red_percent + white_percent
    
    symptoms = {
        "healthy_green": round(min(100.0, max(0.0, green_percent)), 1),
        "blight_necrosis": round(min(100.0, max(0.0, blight_total)), 1),
        "rust_yellowing": round(min(100.0, max(0.0, yellow_percent)), 1),
        "powdery_white": round(min(100.0, max(0.0, white_percent)), 1),
        "bacterial_spot": round(min(100.0, max(0.0, red_percent)), 1),
    }
    
    # Decision Logic: Healthy vs Diseased
    if total_disease_signal < 9.0 or green_percent >= 82.0:
        confidence = round(min(98.0, 78.0 + (100.0 - total_disease_signal) * 0.18), 1)
        return "Healthy Leaf", confidence, symptoms, "None"
        
    # Determine severity
    if total_disease_signal >= 35.0 or dark_percent > 15.0 or blight_total > 28.0:
        severity = "Severe"
    elif total_disease_signal >= 18.0 or blight_total > 12.0:
        severity = "Moderate"
    else:
        severity = "Mild"

    # Crop-specific diagnosis mapping
    crop = (crop_type or 'Other').capitalize()
    
    # Find dominant symptom
    scores = {
        'blight': blight_total,
        'rust': yellow_percent,
        'mildew': white_percent,
        'spot': red_percent
    }
    dominant_symptom = max(scores, key=scores.get)
    top_score = scores[dominant_symptom]
    
    confidence = round(min(96.0, 62.0 + top_score * 1.4), 1)
    
    if crop == 'Tomato':
        if dominant_symptom == 'spot':
            disease_name = 'Bacterial Leaf Spot'
        elif dominant_symptom == 'rust':
            disease_name = 'Tomato Yellow Leaf Curl'
        else:
            disease_name = 'Tomato Leaf Blight'
            
    elif crop == 'Potato':
        if dominant_symptom == 'blight' and dark_percent > 8.0:
            disease_name = 'Potato Late Blight'
        else:
            disease_name = 'Potato Early Blight'
            
    elif crop == 'Wheat':
        if dominant_symptom == 'mildew':
            disease_name = 'Wheat Powdery Mildew'
        else:
            disease_name = 'Wheat Leaf Rust'
            
    elif crop == 'Rice':
        if dominant_symptom == 'blight':
            disease_name = 'Rice Blast'
        elif dominant_symptom == 'rust':
            disease_name = 'Bacterial Leaf Blight'
        else:
            disease_name = 'Rice Brown Spot'
            
    elif crop == 'Chili':
        if dominant_symptom == 'mildew':
            disease_name = 'Chili Powdery Mildew'
        else:
            disease_name = 'Chili Anthracnose'
            
    elif crop == 'Cotton':
        if dominant_symptom == 'rust':
            disease_name = 'Cotton Leaf Curl'
        else:
            disease_name = 'Cotton Bacterial Blight'
            
    elif crop == 'Sugarcane':
        if dominant_symptom == 'spot' or dark_percent > 10.0:
            disease_name = 'Sugarcane Red Rot'
        else:
            disease_name = 'Sugarcane Rust'
            
    elif crop == 'Maize':
        if dominant_symptom == 'rust':
            disease_name = 'Maize Common Rust'
        else:
            disease_name = 'Northern Corn Leaf Blight'
            
    else:  # 'Other' / General
        if dominant_symptom == 'blight':
            disease_name = 'Leaf Blight'
        elif dominant_symptom == 'rust':
            disease_name = 'Leaf Rust'
        elif dominant_symptom == 'mildew':
            disease_name = 'Powdery Mildew'
        else:
            disease_name = 'Bacterial Leaf Spot'
            
    return disease_name, confidence, symptoms, severity