import pandas as pd
import sqlite3
import os
import shutil
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g, send_file
import logging
import tempfile
from werkzeug.utils import secure_filename


# 로깅 설정
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = "secret_key"

MASTER_PASSWORD = "masterkoo6990@@"
ADMIN_PASSWORD = "admin0123"
VIEWER_PASSWORD = "usp0123"

# 렌더 환경 확인 및 DB 경로 설정
if 'RENDER' in os.environ:
    # 렌더 환경에서는 /opt/render/project/src/data 경로에 저장
    RENDER_DISK_PATH = '/opt/render/project/src/data'
    DB_FILE_PATH = os.path.join(RENDER_DISK_PATH, 'claims.db')
    # EXCEL_FILE_PATH = os.path.join(RENDER_DISK_PATH, 'DB_Excel.xlsx')  # 더 이상 사용하지 않음
    print(f"Running on Render, DB path: {DB_FILE_PATH}")
else:
    # 로컬 환경에서는 C:\Users\dhkoo\product_app 경로 사용
    RENDER_DISK_PATH = r'C:\Users\dhkoo\product_app'
    DB_FILE_PATH = os.path.join(RENDER_DISK_PATH, 'claims.db')
    # EXCEL_FILE_PATH = os.path.join(RENDER_DISK_PATH, 'DB_Excel.xlsx')  # 더 이상 사용하지 않음
    print(f"Running locally, DB path: {DB_FILE_PATH}")

# DB_FILE_PATH 경로에 폴더가 없다면 생성
os.makedirs(os.path.dirname(DB_FILE_PATH), exist_ok=True)

ALLOWED_EXTENSIONS = {'db'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 렌더 환경 확인 및 업로드 폴더 경로 설정
if 'RENDER' in os.environ:
    UPLOAD_FOLDER = '/opt/render/project/src/data'
else:
    UPLOAD_FOLDER = r'C:\Users\dhkoo\product_app'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 업로드 폴더가 존재하지 않으면 생성
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {'db'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# DB 파일이 없으면 복사
def copy_db_files():
    """DB 파일이 지정 경로에 없으면 복사"""
    # if not os.path.exists(EXCEL_FILE_PATH): # 엑셀 파일 관련 코드 제거
    #     shutil.copy('DB_Excel.xlsx', EXCEL_FILE_PATH)
    #     print(f"Excel file copied to {EXCEL_FILE_PATH}")
    if not os.path.exists(DB_FILE_PATH):
        shutil.copy('claims.db', DB_FILE_PATH)
        print(f"DB file copied to {DB_FILE_PATH}")

# 전역 변수 선언 및 초기화 플래그 설정
app_initialized = False

@app.before_request
def before_request_func():
    global app_initialized
    if not app_initialized:
        with app.app_context():
            initialize_database()
            load_configurations()
        app_initialized = True

def initialize_database():
    # 데이터베이스 초기화 코드
    init_db()
    copy_db_files()  # DB 파일 복사
    # migrate_products()  # 마이그레이션  # 엑셀 마이그레이션 제거

def load_configurations():
    # 설정 로드 코드
    pass

@app.before_request
def require_login():
    allowed_routes = ["login", "autocomplete", "static"]
    if "role" not in session and request.endpoint not in allowed_routes and not request.path.startswith('/static'):
        return redirect(url_for("login"))

def get_db():
    """매 요청마다 DB 연결을 생성"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_FILE_PATH)
        db.row_factory = sqlite3.Row  # 컬럼명으로 접근 가능하도록 설정
    return db

@app.teardown_appcontext
def close_connection(exception):
    """요청 종료 시 DB 연결을 닫음"""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    """DB 쿼리 실행 헬퍼 함수"""
    db = get_db()
    cursor = db.execute(query, args)
    rv = cursor.fetchall()
    cursor.close()
    return (rv[0] if rv else None) if one else rv

def reset_db():
    """기존 DB 파일을 삭제하고 새로 생성"""
    db = get_db()
    db.close()  # 먼저 DB 연결을 닫음
    if os.path.exists(DB_FILE_PATH):
        os.remove(DB_FILE_PATH)
    init_db()

def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_code TEXT UNIQUE NOT NULL,
        item_name TEXT,
        description TEXT,
        unit_size TEXT,
        color TEXT,
        weight REAL,
        dosage TEXT,
        remark TEXT
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        claim_main TEXT,
        claim_description TEXT,
        claim_concentration REAL,
        claim_unit TEXT DEFAULT 'mg',
        test_result TEXT,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    )
    ''')
    db.commit()
    cursor.close()

def categorize_item_code(item_code):
    """아이템 코드를 해석하여 제품 유형을 반환"""
    if "A-TB-" in item_code:
        return "Tablet"
    elif "A-SG-" in item_code:
        return "Softgel"
    elif "A-HC-" in item_code:
        return "Hard Capsule"
    elif "A-SH-" in item_code:
        return "Sachet"
    elif "A-PW-" in item_code:
        return "Powder"
    elif "A-LQ-" in item_code:
        return "Liquid"
    elif "PH-TB" in item_code:
        return "PH Tablet"
    elif "PH-HC" in item_code:
        return "PH Hard Capsule"
    elif "PH-SG" in item_code:
        return "PH Softgel"
    else:
        return None

@app.route("/autocomplete", methods=["GET"])
def autocomplete():
    query = request.args.get("query", "").strip()
    field = request.args.get("field", "claim_main")
    main_claim = request.args.get("main_claim", "").strip()  # 필터 기준

    print(f"🔍 Autocomplete 요청: query={query}, field={field}, main_claim={main_claim}")  # 요청 확인

    db = get_db()
    cursor = db.cursor()

    try:
        if field == 'claim_main':
            cursor.execute('''
                SELECT DISTINCT claim_main
                FROM claims
                WHERE claim_main LIKE ?
                ORDER BY claim_main ASC
                LIMIT 10
            ''', ('%' + query + '%',))

        elif field == 'claim_description':
            if main_claim:
                cursor.execute('''
                    SELECT DISTINCT claim_description
                    FROM claims
                    WHERE claim_main = ? AND claim_description LIKE ?
                    ORDER BY claim_description ASC
                    LIMIT 10
                ''', (main_claim, '%' + query + '%',))
            else:
                cursor.execute('''
                    SELECT DISTINCT claim_description
                    FROM claims
                    WHERE claim_description LIKE ?
                    ORDER BY claim_description ASC
                    LIMIT 10
                ''', ('%' + query + '%',))

        elif field in ['item_code', 'item_name', 'description', 'unit_size', 'color']:
            cursor.execute(f'''
                SELECT DISTINCT {field}
                FROM products
                WHERE {field} LIKE ?
                ORDER BY {field} ASC
                LIMIT 50
            ''', ('%' + query + '%',))
        else:
            return jsonify([])

        suggestions = [row[0] for row in cursor.fetchall()]
        print(f"✅ DB 조회 결과: {suggestions}")  # 응답 확인
        return jsonify(suggestions)

    except Exception as e:
        print(f"❌ Autocomplete 오류: {e}")  # 오류 확인
        return jsonify([])

    finally:
        cursor.close()

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if "role" not in session or session["role"] not in ['admin', 'master']:
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    if request.method == 'POST':
        item_code = request.form['item_code']
        item_name = request.form['item_name']
        description = request.form['description']
        unit_size = request.form['unit_size']
        color = request.form['color']
        weight = request.form['weight']
        remark = request.form.get('remark', '')

        # 제품 코드를 기반으로 dosage 설정
        if item_code.startswith('A-TB-'):
            dosage = 'Tablet'
        elif item_code.startswith('A-SG-'):
            dosage = 'Softgel'
        elif item_code.startswith('A-HC-'):
            dosage = 'Hard Capsule'
        elif item_code.startswith('A-SH-'):
            dosage = 'Sachet'
        elif item_code.startswith('A-PW-'):
            dosage = 'Powder'
        elif item_code.startswith('A-LQ-'):
            dosage = 'Liquid'
        elif 'PH-TB-' in item_code:
            dosage = 'PH Tablet'
        elif 'PH-HC-' in item_code:
            dosage = 'PH Hard Capsule'
        elif 'PH-SG-' in item_code:
            dosage = 'PH Softgel'
        else:
            dosage = 'Unknown'

        db = get_db()
        cursor = db.cursor()

        try:
            cursor.execute('''
            INSERT INTO products (item_code, item_name, description, unit_size, color, weight, dosage, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (item_code, item_name, description, unit_size, color, weight, dosage, remark))
            product_id = cursor.lastrowid

            claim_mains = request.form.getlist('claim_main[]')
            claim_descriptions = request.form.getlist('claim_description[]')
            claim_concentrations = request.form.getlist('claim_concentration[]')
            claim_units = request.form.getlist('claim_unit[]')
            test_results = request.form.getlist('test_result[]')

            for i in range(len(claim_mains)):
                claim_main = claim_mains[i]
                claim_description = claim_descriptions[i]
                claim_concentration = claim_concentrations[i]
                claim_unit = claim_units[i] if i < len(claim_units) else 'mg'
                test_result = test_results[i] if i < len(test_results) else None

                if claim_main and claim_description and claim_concentration:
                    cursor.execute('''
                    INSERT INTO claims (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result))

            db.commit()
            flash('Product added successfully!', 'success')

            return redirect(url_for('index'))

        except sqlite3.IntegrityError as e:
            db.rollback()
            if "UNIQUE constraint failed: products.item_code" in str(e):
                flash('Item Code already exists. Please use a unique Item Code.', 'error')
            else:
                flash(f'An error occurred: {str(e)}', 'error')
            return render_template('add.html')

        finally:
            cursor.close()

    claim_unit_options = ['mg', 'mcg', 'IU', 'mgaTE', 'mgRAE', 'mcgRAE', 'mgNE', 'mcgNE', 'mgDFE', 'mcgDFE', 'B cfu']
    test_result_options = ['Test O', 'Test X', 'Input']
    return render_template('add.html', claim_unit_options=claim_unit_options, test_result_options=test_result_options)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form["password"]
        if password == MASTER_PASSWORD:
            session["role"] = "master"
            flash("마스터 계정으로 로그인했습니다!", "success")
            return redirect(url_for("index"))
        elif password == ADMIN_PASSWORD:
            session["role"] = "admin"
            flash("관리자로 로그인했습니다!", "success")
            return redirect(url_for("index"))
        elif password == VIEWER_PASSWORD:
            session["role"] = "viewer"
            flash("열람 전용으로 로그인했습니다!", "info")
            return redirect(url_for("index"))
        else:
            flash("잘못된 비밀번호입니다. 다시 시도하세요.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃했습니다.", "info")
    return redirect(url_for("login"))

@app.route('/edit/<item_code>', methods=['GET', 'POST'])
def edit_product(item_code):
    if "role" not in session or session["role"] not in ['admin', 'master']:
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))
    db = get_db()
    cursor = db.cursor()

    if request.method == 'GET':
        cursor.execute('SELECT * FROM products WHERE item_code = ?', (item_code,))
        product = cursor.fetchone()

        if not product:
            flash("해당 제품을 찾을 수 없습니다.", "danger")
            cursor.close()
            return redirect(url_for("index"))

        cursor.execute('''
        SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
        FROM claims
        LEFT JOIN products ON claims.product_id = products.id
        WHERE products.item_code = ?
        ''', (item_code,))
        claims = cursor.fetchall()

        claim_unit_options = ['mg', 'mcg', 'IU', 'mgaTE', 'mgRAE', 'mcgRAE', 'mgNE', 'mcgNE', 'mgDFE', 'mcgDFE', 'B cfu']
        test_result_options = ['Test O', 'Test X', 'Input']

         # 🔹 추가: 기존 필터 URL을 세션에 저장 (이전 검색 화면 유지)
        if 'filter_url' not in session or request.referrer and 'edit' not in request.referrer:
            session['filter_url'] = request.referrer  # 필터 적용된 목록 페이지 저장

        return render_template('edit.html', product=product, claims=claims, claim_unit_options=claim_unit_options, test_result_options=test_result_options)

    elif request.method == 'POST':
        item_name = request.form.get('item_name', '')
        description = request.form.get('description', '')
        unit_size = request.form.get('unit_size', '')
        color = request.form.get('color', '')
        weight = request.form.get('weight', '')
        dosage = request.form.get('dosage', '')
        remark = request.form.get('remark', '')

        try:
            cursor.execute('''
            UPDATE products SET item_name=?, description=?, unit_size=?, color=?, weight=?, dosage=?, remark=?
            WHERE item_code=?
            ''', (item_name, description, unit_size, color, weight, dosage, remark, item_code))

            cursor.execute('''
            DELETE FROM claims
            WHERE product_id IN (SELECT id FROM products WHERE item_code = ?)
            ''', (item_code,))

            claim_mains = request.form.getlist('claim_main[]')
            claim_descriptions = request.form.getlist('claim_description[]')
            claim_concentrations = request.form.getlist('claim_concentration[]')
            claim_units = request.form.getlist('claim_unit[]')
            test_results = request.form.getlist('test_result[]')

            cursor.execute('SELECT id FROM products WHERE item_code = ?', (item_code,))
            product_id = cursor.fetchone()[0]

            for i in range(len(claim_mains)):
                claim_main = claim_mains[i]
                claim_description = claim_descriptions[i]
                claim_concentration = claim_concentrations[i]
                claim_unit = claim_units[i] if i < len(claim_units) else 'mg'
                test_result = test_results[i] if i < len(test_results) else None

                if claim_main and claim_description and claim_concentration:
                    cursor.execute('''
                    INSERT INTO claims (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result))

            db.commit()
            flash('제품 정보가 수정되었습니다!', 'success')

            # 🔹 추가: 필터 유지된 목록으로 돌아가기
            return redirect(session.get('filter_url', url_for('index')))

            return redirect(url_for('index'))

        except sqlite3.Error as e:
            db.rollback()
            flash(f'오류 발생: {str(e)}', 'danger')
            return render_template('edit.html', product=request.form, claims=[])

        finally:
            cursor.close()

@app.route('/delete/<item_code>')
def delete_product(item_code):
    if "role" not in session or session["role"] not in ['admin', 'master']:
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute('DELETE FROM claims WHERE product_id IN (SELECT id FROM products WHERE item_code = ?)', (item_code,))
        cursor.execute('DELETE FROM products WHERE item_code = ?', (item_code,))

        db.commit()
        flash('제품이 성공적으로 삭제되었습니다!', 'success')

    except sqlite3.Error as e:
        db.rollback()
        flash(f'오류 발생: {str(e)}', 'danger')

    finally:
        cursor.close()

    return redirect(url_for('index'))

@app.route('/')
def index():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT item_code, item_name, description, unit_size, color, weight, dosage, remark FROM products ORDER BY item_code ASC')
    products = cursor.fetchall()
    product_categories = {}
    product_claims = {}

    for product in products:
        item_code = product[0]
        product_categories[item_code] = categorize_item_code(item_code)
        cursor.execute('''
        SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
        FROM claims
        JOIN products ON claims.product_id = products.id
        WHERE products.item_code = ?
        ''', (item_code,))
        product_claims[item_code] = cursor.fetchall()

    # 자동완성을 위한 데이터 준비
    cursor.execute('SELECT DISTINCT claim_main FROM claims ORDER BY claim_main ASC')
    claim_main_options = [row[0] for row in cursor.fetchall()]

    cursor.execute('SELECT DISTINCT item_name FROM products ORDER BY item_name ASC')
    item_name_options = [row[0] for row in cursor.fetchall()]

    # 자동 완성을 위한 데이터베이스 쿼리 추가
    item_code_options = [row[0] for row in cursor.execute('SELECT DISTINCT item_code FROM products ORDER BY item_code ASC').fetchall()]
    item_name_options = [row[0] for row in cursor.execute('SELECT DISTINCT item_name FROM products ORDER BY item_name ASC').fetchall()]
    description_options = [row[0] for row in cursor.execute('SELECT DISTINCT description FROM products ORDER BY description ASC').fetchall()]
    unit_size_options = [row[0] for row in cursor.execute('SELECT DISTINCT unit_size FROM products ORDER BY unit_size ASC').fetchall()]
    color_options = [row[0] for row in cursor.execute('SELECT DISTINCT color FROM products ORDER BY color ASC').fetchall()]

    # 단위 옵션 추가
    claim_unit_options = ['mg', 'mcg', 'IU', 'mgaTE', 'mgRAE', 'mcgRAE', 'mgNE', 'mcgNE', 'mgDFE', 'mcgDFE', 'B cfu']

    return render_template('index.html', products=products, product_claims=product_claims, product_categories=product_categories, claim_main_options=claim_main_options,
                           item_name_options=item_name_options, item_code_options=item_code_options,
                           description_options=description_options, unit_size_options=unit_size_options,
                           color_options=color_options, claim_unit_options=claim_unit_options, search_filters={})

@app.route('/search', methods=['GET'])
def search_products():
    # 검색 필터 초기화
    filters = {
        "item_code": request.args.get("item_code", None),
        "item_name": request.args.get("item_name", None),
        "description": request.args.get("description", None),
        "unit_size": request.args.get("unit_size", None),
        "color": request.args.get("color", None),
        "weight": request.args.get("weight", None),
        "dosage": request.args.get("dosage", None),
        "claim_main": request.args.getlist("claim_main[]"),
        "claim_description": request.args.getlist("claim_description[]"),
        "claim_concentration": request.args.getlist("claim_concentration[]"),
        "claim_concentration_tolerance": request.args.getlist("claim_concentration_tolerance[]", type=float),
        "claim_unit": request.args.getlist("claim_unit[]"),
        "product_type": request.args.get("product_type", None),
        "weight_tolerance": request.args.get("weight_tolerance", "10"),
        "all_unit": "all_unit" in request.args # 수정됨
    }

    filters = {k: v for k, v in filters.items() if v is not None and (isinstance(v, list) or str(v).strip() != "")}

    db = get_db()
    cursor = db.cursor()

    base_query = """
    SELECT DISTINCT p.item_code, p.item_name, p.description, p.unit_size, p.color, p.weight, p.dosage, p.remark
    FROM products p
    WHERE 1=1
    """

    params = {}

    # Weight 필터
    if "weight" in filters:
        try:
            weight_value = float(filters["weight"])
            weight_tolerance = float(filters.get("weight_tolerance", "10"))
            min_weight = weight_value * (1 - weight_tolerance / 100)
            max_weight = weight_value * (1 + weight_tolerance / 100)
            base_query += " AND p.weight BETWEEN :min_weight AND :max_weight"
            params["min_weight"] = min_weight
            params["max_weight"] = max_weight
        except ValueError:
            pass

    # 일반 필터 추가
    for field, value in filters.items():
        if field not in ["weight", "claim_concentration", "claim_concentration_tolerance", "claim_main",
                         "claim_description", "claim_unit", "dosage", "product_type", "weight_tolerance", "all_unit"]:
            base_query += f" AND p.{field} LIKE :{field}"
            params[field] = f"%{value}%"

    # Claim 필터 개선 (단위 변환 포함)
    if "claim_main" in filters or "claim_description" in filters or "claim_concentration" in filters or "claim_unit" in filters:
        claim_conditions = []
        claim_mains = filters.get("claim_main", [])
        claim_descriptions = filters.get("claim_description", [])
        claim_concentrations = filters.get("claim_concentration", [])
        claim_concentration_tolerances = filters.get("claim_concentration_tolerance", [])
        claim_units = filters.get("claim_unit", [])
        all_unit = filters.get("all_unit")

        # 단위 변환 맵 
        unit_conversion_map = {
        "mg": [
                ("mcg", 1000),
                ("mgDFE", 1.7),
                ("mcgDFE", 1700),
                ("mgaTE", 1),
                ("mgRAE", 1),
                ("mcgRAE", 1000),
                ("mgNE", 1),
                ("mcgNE", 1000)
        ],
        "mcg": [
                ("mg", 0.001),
                ("mgDFE", 0.0017),
                ("mgaTE", 0.001),
                ("mgRAE", 0.001),
                ("mcgRAE", 1),
                ("mgNE", 0.001),
                ("mcgDFE", 1.7)
        ],
        "mgNE": [
                ("mgNE", 1),
                ("mcgNE", 1000),
                ("mg", 1)
        ],
        "mcgNE": [
                ("mgcNE", 1),
                ("mgNE", 0.001),
                ("mg", 0.001)
        ],
        "mgDFE": [
                ("mg", 1/1.7),
                ("mgDFE", 1),
                ("mcgDFE", 1000),
                ("mcg", 1/1700)
        ],
        "mcgDFE": [
                ("mcgDFE", 1),
                ("mgDFE", 0.001),
                ("mcg", 1.7)
        ],
        "mgaTE": [
                ("mgaTE", 1),
                ("mg", 1),
                ("mcg", 1000)
        ],
        "mgRAE": [
                ("mgRAE", 1),
                ("mcgRAE", 1000),
                ("mg", 1)
        ],
        "mcgRAE": [
                ("mcgRAE", 1),
                ("mgRAE", 0.001),
                ("mcg", 1)
        ]
    }

        for i in range(max(len(claim_mains), len(claim_descriptions), len(claim_concentrations), len(claim_units))):
            condition = []

            if i < len(claim_mains) and claim_mains[i]:
                condition.append(f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_main LIKE :claim_main_{i})")
                params[f"claim_main_{i}"] = f"%{claim_mains[i]}%"

            if i < len(claim_descriptions) and claim_descriptions[i]:
                condition.append(f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_description LIKE :claim_desc_{i})")
                params[f"claim_desc_{i}"] = f"%{claim_descriptions[i]}%"

            if i < len(claim_concentrations) and claim_concentrations[i]:
                try:
                    concentration_value = float(claim_concentrations[i])

                    # 0 이하의 값 검색 방지
                    if concentration_value <= 0:
                        raise ValueError("검색값은 0보다 커야 합니다.")

                    tolerance = float(claim_concentration_tolerances[i]) if i < len(claim_concentration_tolerances) and claim_concentration_tolerances[i] is not None else 10.0

                    min_concentration = concentration_value * (1 - tolerance / 100)
                    max_concentration = concentration_value * (1 + tolerance / 100)

                    unit_condition = []

                    # 단위 변환 로직 (수정됨: 2차 변환까지 적용)
                    if all_unit:
                        for original_unit, first_conversions in unit_conversion_map.items():
                            # 1차 변환
                            for converted_unit1, factor1 in first_conversions:
                                converted_value1 = concentration_value * factor1
                                converted_min1 = converted_value1 * (1 - tolerance / 100)
                                converted_max1 = converted_value1 * (1 + tolerance / 100)

                                unit_condition.append(create_unit_condition(i, original_unit, converted_unit1, converted_min1, converted_max1))
                                params.update(create_unit_params(i, original_unit, converted_unit1, converted_min1, converted_max1))

                                # 2차 변환
                                if converted_unit1 in unit_conversion_map:
                                    for converted_unit2, factor2 in unit_conversion_map[converted_unit1]:
                                        converted_value2 = converted_value1 * factor2
                                        converted_min2 = converted_value2 * (1 - tolerance / 100)
                                        converted_max2 = converted_value2 * (1 + tolerance / 100)

                                        unit_condition.append(create_unit_condition(i, converted_unit1, converted_unit2, converted_min2, converted_max2))
                                        params.update(create_unit_params(i, converted_unit1, converted_unit2, converted_min2, converted_max2))

                    elif i < len(claim_units):
                        original_unit = claim_units[i]

                        if original_unit in unit_conversion_map:
                            # 1차 변환
                            for converted_unit1, factor1 in unit_conversion_map[original_unit]:
                                converted_value1 = concentration_value * factor1
                                converted_min1 = converted_value1 * (1 - tolerance / 100)
                                converted_max1 = converted_value1 * (1 + tolerance / 100)

                                unit_condition.append(create_unit_condition(i, original_unit, converted_unit1, converted_min1, converted_max1))
                                params.update(create_unit_params(i, original_unit, converted_unit1, converted_min1, converted_max1))

                                # 2차 변환
                                if converted_unit1 in unit_conversion_map:
                                    for converted_unit2, factor2 in unit_conversion_map[converted_unit1]:
                                        converted_value2 = converted_value1 * factor2
                                        converted_min2 = converted_value2 * (1 - tolerance / 100)
                                        converted_max2 = converted_value2 * (1 + tolerance / 100)

                                        unit_condition.append(create_unit_condition(i, converted_unit1, converted_unit2, converted_min2, converted_max2))
                                        params.update(create_unit_params(i, converted_unit1, converted_unit2, converted_min2, converted_max2))
                        else:
                            unit_condition.append(f"""
                                EXISTS (
                                    SELECT 1
                                    FROM claims c{i}
                                    WHERE c{i}.product_id = p.id
                                    AND c{i}.claim_concentration BETWEEN :min_conc_{i} AND :max_conc_{i}
                                    AND c{i}.claim_unit = :claim_unit_{i}
                                )
                            """)
                            params[f"min_conc_{i}"] = min_concentration
                            params[f"max_conc_{i}"] = max_concentration
                            params[f"claim_unit_{i}"] = original_unit

                    if unit_condition:
                        condition.append(f"({' OR '.join(unit_condition)})")

                except ValueError:
                    condition.append(f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_concentration LIKE :claim_conc_{i})")
                    params[f"claim_conc_{i}"] = f"%{claim_concentrations[i]}%"

            if condition:
                claim_conditions.append(" AND ".join(condition))

        if claim_conditions:
            base_query += " AND (" + " OR ".join(claim_conditions) + ")"

    query = base_query + " ORDER BY p.item_code ASC"

    print("쿼리:", query)
    print("파라미터:", params)
    cursor.execute(query, params)
    products = cursor.fetchall()

    # 제품 유형 필터링 적용 (Python에서 필터링)
    if "product_type" in filters and filters["product_type"]:
        products = [p for p in products if categorize_item_code(p[0]) == filters["product_type"]]

    # 제품 유형을 저장할 딕셔너리
    product_categories = {}
    for product in products:
        product_categories[product[0]] = categorize_item_code(product[0])

    product_claims = {}
    for product in products:
        cursor.execute('''
        SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
        FROM claims
        JOIN products ON claims.product_id = products.id
        WHERE products.item_code = ?
        ''', (product[0],))
        claims = cursor.fetchall()
        product_claims[product[0]] = claims

    # 자동완성을 위한 데이터 준비
    cursor.execute('SELECT DISTINCT claim_main FROM claims ORDER BY claim_main ASC')
    claim_main_options = [row[0] for row in cursor.fetchall()]

    cursor.execute('SELECT DISTINCT item_name FROM products ORDER BY item_name ASC')
    item_name_options = [row[0] for row in cursor.fetchall()]

    # 자동 완성을 위한 데이터베이스 쿼리 추가
    item_code_options = [row[0] for row in cursor.execute('SELECT DISTINCT item_code FROM products ORDER BY item_code ASC').fetchall()]
    description_options = [row[0] for row in cursor.execute('SELECT DISTINCT description FROM products ORDER BY description ASC').fetchall()]
    unit_size_options = [row[0] for row in cursor.execute('SELECT DISTINCT unit_size FROM products ORDER BY unit_size ASC').fetchall()]
    color_options = [row[0] for row in cursor.execute('SELECT DISTINCT color FROM products ORDER BY color ASC').fetchall()]

    # 단위 옵션 추가
    claim_unit_options = ['mg', 'mcg', 'IU', 'mgaTE', 'mgRAE', 'mcgRAE', 'mgNE', 'mcgNE', 'mgDFE', 'mcgDFE', 'B cfu']

    return render_template('index.html', products=products, product_claims=product_claims,
                           product_categories=product_categories, search_filters=filters,
                           claim_main_options=claim_main_options, item_name_options=item_name_options,
                           item_code_options=item_code_options, description_options=description_options,
                           unit_size_options=unit_size_options, color_options=color_options,
                           claim_unit_options=claim_unit_options)

def create_unit_condition(i, original_unit, converted_unit, converted_min, converted_max):
    return f"""
        EXISTS (
            SELECT 1
            FROM claims c{i}
            WHERE c{i}.product_id = p.id
            AND c{i}.claim_concentration BETWEEN :min_conc_{i}_{original_unit}_{converted_unit} AND :max_conc_{i}_{original_unit}_{converted_unit}
            AND c{i}.claim_unit = :claim_unit_{converted_unit}
        )
    """

def create_unit_params(i, original_unit, converted_unit, converted_min, converted_max):
    return {
        f"min_conc_{i}_{original_unit}_{converted_unit}": converted_min,
        f"max_conc_{i}_{original_unit}_{converted_unit}": converted_max,
        f"claim_unit_{converted_unit}": converted_unit
    }


@app.route('/clear')
def clear_search():
    return redirect(url_for('index'))

@app.route('/check_db_exists', methods=['GET'])
def check_db_exists():
    """기존 DB 파일이 있는지 확인"""
    if 'RENDER' in os.environ:
        db_path = '/opt/render/project/src/data/claims.db'
    else:
        db_path = r'C:\Users\dhkoo\product_app\claims.db'

    return jsonify({"exists": os.path.exists(db_path)})

import os
import shutil
from flask import Flask, request, redirect, url_for, flash, session

@app.route('/save_db', methods=['POST'])
def save_db():
    """현재 DB를 저장하여 claims.db 파일을 덮어쓰기"""
    if "role" not in session or session["role"] not in ["admin", "master"]:
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    try:
        # 환경에 따라 DB 저장 경로 설정
        if 'RENDER' in os.environ:
            db_path = '/opt/render/project/src/data/claims.db'
        else:
            db_path = r'C:\Users\dhkoo\product_app\claims.db'

        backup_path = db_path + ".bak"  # 기존 DB 백업 파일 경로
        temp_path = db_path + ".tmp"  # 임시 저장 파일 경로

        # 🔹 현재 DB 연결 닫기 (파일 사용 중 문제 방지)
        if hasattr(g, '_database'):
            g._database.close()
            g._database = None

        # 🔹 기존 DB를 백업
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)  # 기존 DB 백업

        # 🔹 새로운 DB를 저장하기 전에 임시 파일로 먼저 저장
        shutil.copy2(db_path, temp_path)

        # 🔹 저장된 파일이 올바른 SQLite 데이터베이스인지 확인
        try:
            conn = sqlite3.connect(temp_path)
            conn.execute("PRAGMA integrity_check")  # 데이터베이스 무결성 체크
            conn.close()
        except sqlite3.DatabaseError:
            flash("Error: 저장된 파일이 유효한 SQLite 데이터베이스가 아닙니다.", "danger")
            os.remove(temp_path)  # 손상된 파일 삭제
            return redirect(url_for("index"))

        # 🔹 검증된 DB 파일을 기존 위치에 저장
        shutil.move(temp_path, db_path)

        flash(f"Database saved successfully at: {db_path}", "success")

        # 🔹 DB 경로 재설정 (추후 사용을 위해)
        global DB_FILE_PATH
        DB_FILE_PATH = db_path

        # 🔹 DB 연결을 초기화하여 새로운 DB 파일 사용
        if hasattr(g, '_database'):
            g._database.close()
            g._database = None

    except Exception as e:
        flash(f"Error saving database: {str(e)}", "danger")

    return redirect(url_for("index"))

@app.route('/download_db')
def download_db():
    if "role" not in session or session["role"] not in ["master"]:
        flash("마스터 권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    """claims.db 파일을 다운로드"""
    return send_file(DB_FILE_PATH, as_attachment=True, download_name='claims.db')

@app.route('/compare', methods=['POST'])
def compare_products():
    selected_products = request.form.getlist('item_code[]')
    db = get_db()
    cursor = db.cursor()
    products = []
    claims = {}

    # 🔹 기존 필터 URL을 세션에 저장 (이전 검색 화면 유지)
    if 'filter_url' not in session or request.referrer and 'compare' not in request.referrer:
        session['filter_url'] = request.referrer  # 검색 필터 적용된 목록 저장

    for item_code in selected_products:
        cursor.execute('''
        SELECT item_code, item_name, description, unit_size, color, weight, dosage, remark
        FROM products
        WHERE item_code = ?
        ''', (item_code,))
        product = cursor.fetchone()
        if product:
            products.append(product)

        cursor.execute('''
        SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
        FROM claims
        JOIN products ON claims.product_id = products.id
        WHERE products.item_code = ?
        ''', (item_code,))
        product_claims = cursor.fetchall()
        claims[item_code] = product_claims

    # 🔹 Compare 페이지 렌더링 (즉시 리디렉션 X)
    return render_template('compare.html', products=products, claims=claims, filter_url=session.get('filter_url', url_for('index')))


@app.route('/view/<item_code>')
def view_product(item_code):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT * FROM products WHERE item_code = ?', (item_code,))
    product = cursor.fetchone()

    if not product:
        flash("해당 제품을 찾을 수 없습니다.", "danger")
        return redirect(url_for("index"))

    cursor.execute('''
    SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
    FROM claims
    LEFT JOIN products ON claims.product_id = products.id
    WHERE products.item_code = ?
    ''', (item_code,))
    claims = cursor.fetchall()

    return render_template('view.html', product=product, claims=claims)

@app.route('/find_db', methods=['GET', 'POST'])
def find_db():
    if "role" not in session or session["role"] not in ["master"]:
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            # 환경에 따른 경로 설정
            if 'RENDER' in os.environ:
                upload_folder = '/opt/render/project/src/data'
            else:
                upload_folder = r'C:\Users\dhkoo\product_app'
            
            os.makedirs(upload_folder, exist_ok=True)
            
            # 항상 'claims.db'로 저장
            file_path = os.path.join(upload_folder, 'claims.db')
            backup_path = os.path.join(upload_folder, 'claims_backup.db')
            
            try:
                # 현재 DB 백업
                if os.path.exists(file_path):
                    shutil.copy2(file_path, backup_path)
                
                # 새 DB 파일 저장
                file.save(file_path)
                
                flash('Database uploaded and replaced successfully', 'success')
                
                # 데이터베이스 연결 재초기화
                if hasattr(g, '_database'):
                    g._database.close()
                    g._database = None
                
                # DB_FILE_PATH 전역 변수 업데이트
                global DB_FILE_PATH
                DB_FILE_PATH = file_path
                
            except Exception as e:
                # 오류 발생 시 백업 복원
                if os.path.exists(backup_path):
                    shutil.copy2(backup_path, file_path)
                flash(f'Error occurred: {str(e)}. Original database restored.', 'error')
            
            finally:
                # 백업 파일 정리
                if os.path.exists(backup_path):
                    os.remove(backup_path)
            
            return redirect(url_for('index'))
    
    return render_template('find db.html')

if __name__ == '__main__':
    app.run(debug=True)