import pandas as pd
import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

app = Flask(__name__)
app.secret_key = "secret_key"

ADMIN_PASSWORD = "admin0123"
VIEWER_PASSWORD = "usp0123"

@app.before_request
def require_login():
    allowed_routes = ["login", "autocomplete", "static"]
    if "role" not in session and request.endpoint not in allowed_routes and not request.path.startswith('/static'):
        return redirect(url_for("login"))

EXCEL_FILE_PATH = "DB_Excel.xlsx"
DB_FILE_PATH = "claims.db"

def reset_db():
    """기존 DB 파일을 삭제하고 새로 생성"""
    if os.path.exists(DB_FILE_PATH):
        os.remove(DB_FILE_PATH)
    init_db()

def init_db():
    """SQLite DB 초기화"""
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()

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

    # claims 테이블에 claim_unit 및 test_result 컬럼 추가
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        claim_main TEXT,
        claim_description TEXT,
        claim_concentration REAL,
        claim_unit TEXT DEFAULT 'mg',  -- 기본값으로 'mg' 설정
        test_result TEXT,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    )
    ''')

    conn.commit()
    conn.close()

def migrate_products():
    """엑셀 데이터 불러와 SQLite에 저장"""
    df = pd.read_excel(EXCEL_FILE_PATH, dtype=str).fillna("")
    df.columns = df.columns.str.strip().str.lower()
    if "dosage" not in df.columns:
        raise KeyError("Column 'Dosage' not found in Excel file.")
    if "weight" in df.columns:
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0)
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    # 기존 테이블에 REMARK 컬럼이 없으면 추가
    cursor.execute("PRAGMA table_info(products)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    if "remark" not in existing_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN remark TEXT")
    conn.commit()
    for _, row in df.iterrows():
        try:
            cursor.execute('''
            INSERT OR REPLACE INTO products (item_code, item_name, description, unit_size, color, weight, dosage, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (row.get("item code", ""), row.get("item name", ""), row.get("description", ""),
                row.get("unit size", ""), row.get("color", ""), row.get("weight", 0), row.get("dosage", ""), row.get("remark", "")))
            conn.commit()
            product_id = cursor.execute("SELECT id FROM products WHERE item_code = ?", (row.get("item code", ""),)).fetchone()[0]

            # 엑셀에서 claim 정보를 가져와서 claims 테이블 업데이트 또는 삽입
            claim_main = row.get("claim main", "")
            claim_description = row.get("claim description", "")
            claim_concentration = row.get("claim concentration", "")
            claim_unit = row.get("claim unit", "mg")  # 기본값 설정
            test_result = row.get("test result", "")

            if claim_main and claim_description and claim_concentration:
                try:
                    cursor.execute('''
                    INSERT OR REPLACE INTO claims (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result))
                    conn.commit()
                except sqlite3.Error as e:
                    print(f"claim 정보 업데이트 중 오류 발생: {e}")

        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: products.item_code" in str(e):
                print(f"Skipping row due to duplicate item_code: {row.get('item code', '')}")
            else:
                raise e
    conn.close()
    print("✅ 제품 및 claim 정보가 업데이트되었습니다.")

def categorize_item_code(item_code):
    """아이템 코드를 해석하여 제품 유형을 반환"""
    parts = item_code.split('-') # '-' 기준으로 분할
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
    main_claim = request.args.get("main_claim", "")
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
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
            ''', (main_claim, '%' + query + '%'))
        else:
            cursor.execute('''
            SELECT DISTINCT claim_description
            FROM claims
            WHERE claim_description LIKE ?
            ORDER BY claim_description ASC
            LIMIT 10
            ''', ('%' + query + '%',))
    else:  # 다른 필드에 대한 자동 완성 처리
        table = 'products'
        column = field
        cursor.execute(f'''
            SELECT DISTINCT {column}
            FROM {table}
            WHERE {column} LIKE ?
            ORDER BY {column} ASC
            LIMIT 10
        ''', ('%' + query + '%',))
    suggestions = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(suggestions)

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if "role" not in session or session["role"] != "admin":
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

        conn = sqlite3.connect(DB_FILE_PATH)
        cursor = conn.cursor()

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

            conn.commit()
            flash('Product added successfully!', 'success')
            return redirect(url_for('index'))

        except sqlite3.IntegrityError as e:
            conn.rollback()
            if "UNIQUE constraint failed: products.item_code" in str(e):
                flash('Item Code already exists. Please use a unique Item Code.', 'error')
            else:
                flash(f'An error occurred: {str(e)}', 'error')
            return render_template('add.html')

        finally:
            conn.close()

    claim_unit_options = ['mg', 'IU', 'mga-TE', 'mgRAE', 'mgNE', 'mgDFE']
    test_result_options = ['Test O', 'Test X', 'Input']
    return render_template('add.html', claim_unit_options=claim_unit_options, test_result_options=test_result_options)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form["password"]
        if password == ADMIN_PASSWORD:
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

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("role", None)
    flash("로그아웃했습니다.", "info")
    return redirect(url_for("login"))

@app.route('/edit/<item_code>', methods=['GET', 'POST'])
def edit_product(item_code):
    if "role" not in session or session["role"] != "admin":
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute('SELECT * FROM products WHERE item_code = ?', (item_code,))
        product = cursor.fetchone()

        if not product:
            flash("해당 제품을 찾을 수 없습니다.", "danger")
            conn.close()
            return redirect(url_for("index"))

        # claim_unit, test_result 추가
        cursor.execute('''
        SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
        FROM claims
        LEFT JOIN products ON claims.product_id = products.id
        WHERE products.item_code = ?
        ''', (item_code,))
        claims = cursor.fetchall()

        conn.close()

        # 단위 옵션과 테스트 결과 옵션 추가
        claim_unit_options = ['mg', 'IU', 'mga-TE', 'mgRAE', 'mgNE', 'mgDFE']
        test_result_options = ['Test O', 'Test X', 'Input']
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

            # 기존 클레임 삭제
            cursor.execute('''
            DELETE FROM claims
            WHERE product_id IN (SELECT id FROM products WHERE item_code = ?)
            ''', (item_code,))

            # 새 클레임 추가
            claim_mains = request.form.getlist('claim_main[]')
            claim_descriptions = request.form.getlist('claim_description[]')
            claim_concentrations = request.form.getlist('claim_concentration[]')
            claim_units = request.form.getlist('claim_unit[]')  # 클레임 단위 추가
            test_results = request.form.getlist('test_result[]')  # 테스트 결과 추가

            cursor.execute('SELECT id FROM products WHERE item_code = ?', (item_code,))
            product_id = cursor.fetchone()

            if product_id:
                product_id = product_id[0]
                for i in range(len(claim_mains)):
                    claim_main = claim_mains[i]
                    claim_description = claim_descriptions[i]
                    claim_concentration = claim_concentrations[i]
                    claim_unit = claim_units[i] if i < len(claim_units) else 'mg'  # 단위가 없는 경우 기본값 'mg' 사용
                    test_result = test_results[i] if i < len(test_results) else None  # 테스트 결과가 없는 경우 None 사용

                    if claim_main and claim_description and claim_concentration:
                        cursor.execute('''
                        INSERT INTO claims (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''', (product_id, claim_main, claim_description, claim_concentration, claim_unit, test_result))

            conn.commit()
            flash('제품 정보가 수정되었습니다!', 'success')
            return redirect(url_for('index'))

        except sqlite3.Error as e:
            conn.rollback()
            flash(f'오류 발생: {str(e)}', 'danger')
            return render_template('edit.html', product=request.form, claims=[])

        finally:
            conn.close()

@app.route('/delete/<item_code>')
def delete_product(item_code):
    if "role" not in session or session["role"] != "admin":
        flash("권한이 없습니다.", "danger")
        return redirect(url_for("index"))

    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()

    try:
        # 제품 삭제 전에 연결된 클레임 먼저 삭제
        cursor.execute('DELETE FROM claims WHERE product_id IN (SELECT id FROM products WHERE item_code = ?)', (item_code,))

        # 제품 삭제
        cursor.execute('DELETE FROM products WHERE item_code = ?', (item_code,))

        conn.commit()
        flash('제품이 성공적으로 삭제되었습니다!', 'success')

    except sqlite3.Error as e:
        conn.rollback()
        flash(f'오류 발생: {str(e)}', 'danger')

    finally:
        conn.close()

    return redirect(url_for('index'))

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

@app.route('/')
def index():
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT item_code, item_name, description, unit_size, color, weight, dosage, remark FROM products ORDER BY item_code ASC')
    products = cursor.fetchall()
    products = [(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7] if p[7] is not None else '') for p in products]
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
    conn.close()
    return render_template('index.html', products=products, product_claims=product_claims, product_categories=product_categories, search_filters=request.args)

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
        "claim_unit": request.args.getlist("claim_unit[]"),  # 클레임 단위 추가
        "product_type": request.args.get("product_type", None),
        "weight_tolerance": request.args.get("weight_tolerance", "10"),
        "all_unit": request.args.get("all_unit", False, type=lambda v: v.lower() == 'true')  # All Unit 옵션 추가
    }

    # 검색 필터에서 None 값인 필터 제거
    filters = {k: v for k, v in filters.items() if v is not None and (isinstance(v, list) or str(v).strip() != "")}

    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()

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

    # 나머지 필터들
    for field, value in filters.items():
        if field not in ["weight", "claim_concentration", "claim_concentration_tolerance", "claim_main",
                         "claim_description", "claim_unit", "dosage", "product_type", "weight_tolerance", "all_unit"]:
            if value != "" and value is not None:
                base_query += f" AND p.{field} LIKE :{field}"
                params[field] = f"%{value}%"

    # Dosage 필터
    if "dosage" in filters:
        base_query += f" AND p.dosage LIKE :dosage"
        params["dosage"] = f"%{filters['dosage']}%"

    # 제품 유형 필터 추가
    if "product_type" in filters:
        product_type = filters["product_type"]
        if product_type == "Tablet":
            base_query += " AND p.item_code LIKE :product_type"
            params["product_type"] = "%-TB-%"
        elif product_type == "Softgel":
            base_query += " AND p.item_code LIKE :product_type"
            params["product_type"] = "%-SG-%"
        elif product_type == "HardCapsule":
            base_query += " AND p.item_code LIKE :product_type"
            params["product_type"] = "%-HC-%"
        elif product_type == "Sachet":
            base_query += " AND p.item_code LIKE :product_type"
            params["product_type"] = "%-SH-%"
        elif product_type == "Powder":
            base_query += " AND p.item_code LIKE :product_type"
            params["product_type"] = "%-PW-%"
        elif product_type == "Liquid":
            base_query += f" AND p.item_code LIKE :product_type"
            params["product_type"] = "%-LQ-%"
        elif product_type == "PH Tablet":
            base_query += f" AND p.item_code LIKE :product_type"
            params["product_type"] = "PH-TB%"
        elif product_type == "PH Hard Capsule":
            base_query += f" AND p.item_code LIKE :product_type"
            params["product_type"] = "PH-HC%"
        elif product_type == "PH Softgel":
            base_query += f" AND p.item_code LIKE :product_type"
            params["product_type"] = "PH-SG%"

    # Claim 필터
    if "claim_main" in filters or "claim_description" in filters or "claim_concentration" in filters or "claim_unit" in filters:
        claim_conditions = []
        claim_mains = filters.get("claim_main", [])
        claim_descriptions = filters.get("claim_description", [])
        claim_concentrations = filters.get("claim_concentration", [])
        claim_concentration_tolerances = filters.get("claim_concentration_tolerance", [])
        claim_units = filters.get("claim_unit", [])  # 클레임 단위 추가
        all_unit = filters.get("all_unit")  # All Unit 옵션 가져오기

        for i in range(max(len(claim_mains), len(claim_descriptions), len(claim_concentrations), len(claim_units))):
            condition = []
            if i < len(claim_mains) and claim_mains[i]:
                condition.append(
                    f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_main LIKE :claim_main_{i})")
                params[f"claim_main_{i}"] = f"%{claim_mains[i]}%"

            if i < len(claim_descriptions) and claim_descriptions[i]:
                condition.append(
                    f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_description LIKE :claim_desc_{i})")
                params[f"claim_desc_{i}"] = f"%{claim_descriptions[i]}%"

            if i < len(claim_concentrations) and claim_concentrations[i]:
                try:
                    concentration_value = float(claim_concentrations[i])
                    # claim_concentration_tolerances 리스트에 값이 있는지 확인
                    if claim_concentration_tolerances and i < len(
                            claim_concentration_tolerances) and claim_concentration_tolerances[i] is not None:
                        tolerance = float(claim_concentration_tolerances[i])
                    else:
                        tolerance = 10.0

                    min_concentration = concentration_value * (1 - tolerance / 100)
                    max_concentration = concentration_value * (1 + tolerance / 100)

                    condition.append(
                        f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_concentration BETWEEN :min_conc_{i} AND :max_conc_{i})")
                    params[f"min_conc_{i}"] = min_concentration
                    params[f"max_conc_{i}"] = max_concentration
                except ValueError:
                    pass

            # 클레임 단위 조건 추가 (All Unit이 선택되지 않았을 때만)
            if not all_unit and i < len(claim_units) and claim_units[i]:
                condition.append(
                    f"EXISTS (SELECT 1 FROM claims c{i} WHERE c{i}.product_id = p.id AND c{i}.claim_unit = :claim_unit_{i})")
                params[f"claim_unit_{i}"] = claim_units[i]

            if condition:
                claim_conditions.append(" AND ".join(condition))

        if claim_conditions:
            base_query += " AND (" + " AND ".join(claim_conditions) + ")"

    query = base_query + " ORDER BY p.item_code ASC"

    print("쿼리:", query)  # 쿼리 출력
    print("파라미터:", params)  # 파라미터 출력

    cursor.execute(query, params)
    products = cursor.fetchall()

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

    conn.close()

    # 단위 옵션 추가
    claim_unit_options = ['mg', 'IU', 'mga-TE', 'mgRAE', 'mgNE', 'mgDFE']

    return render_template('index.html', products=products, product_claims=product_claims,
                           product_categories=product_categories, search_filters=filters,
                           claim_main_options=claim_main_options, item_name_options=item_name_options,
                           item_code_options=item_code_options, description_options=description_options,
                           unit_size_options=unit_size_options, color_options=color_options,  # 자동완성 옵션 추가
                           claim_unit_options=claim_unit_options)  # 단위 옵션 전달

@app.route('/clear')
def clear_search():
    return redirect(url_for('index'))

@app.route('/compare', methods=['POST'])
def compare_products():
    selected_products = request.form.getlist('item_code[]')
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    products = []
    claims = {}
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
    conn.close()
    return render_template('compare.html', products=products, claims=claims)

# 새로운 뷰 페이지 라우트
@app.route('/view/<item_code>')
def view_product(item_code):
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM products WHERE item_code = ?', (item_code,))
    product = cursor.fetchone()

    if not product:
        flash("해당 제품을 찾을 수 없습니다.", "danger")
        conn.close()
        return redirect(url_for("index"))

    cursor.execute('''
    SELECT claim_main, claim_description, claim_concentration, claim_unit, test_result
    FROM claims
    LEFT JOIN products ON claims.product_id = products.id
    WHERE products.item_code = ?
    ''', (item_code,))
    claims = cursor.fetchall()

    conn.close()

    return render_template('view.html', product=product, claims=claims)

if __name__ == "__main__":
    db_exists = os.path.exists(DB_FILE_PATH)
    init_db()  # 테이블 초기화 (이미 존재하면 아무 작업도 안 함)
    if not db_exists:
        migrate_products()  # 엑셀 데이터 마이그레이션
        print("✅ Database initialized and data migrated successfully!")
    else:
        conn = sqlite3.connect(DB_FILE_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(products)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'dosage' not in columns:
            try:
                cursor.execute("ALTER TABLE products ADD COLUMN dosage TEXT")
                conn.commit()
                print("✅ Dosage column added successfully!")
            except sqlite3.Error as e:
                print(f"❗ Error adding dosage column: {e}")
        else:
            print("✅ Dosage column already exists.")
        if 'remark' not in columns:
            try:
                cursor.execute("ALTER TABLE products ADD COLUMN remark TEXT")
                conn.commit()
                print("✅ Remark column added successfully!")
            except sqlite3.Error as e:
                print(f"❗ Error adding remark column: {e}")
        else:
            print("✅ Remark column already exists.")
        conn.close()
        print("✅ Database exists. Updating with latest Excel data.")
        migrate_products()  # 엑셀 데이터로 기존 DB 업데이트
    app.run(debug=True)
