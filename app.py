import os
import json
import re
import uuid
from datetime import datetime
from flask import Flask, render_template, request, send_file, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from utils.pdf_processor import process_pdf, generate_stats, extract_students_from_pdf
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import pandas as pd
import shutil
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key_change_me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = None

# Mail Configuration (Example - Update with real SMTP)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)
s = URLSafeTimedSerializer(app.secret_key)

HISTORY_FILE = os.path.join(app.config['UPLOAD_FOLDER'], 'history.json')

# User Model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True) # Nullable for OAuth users
    name = db.Column(db.String(100), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# History Management Helpers
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r') as f:
            all_history = json.load(f)
            # Filter history by current user if logged in
            if current_user.is_authenticated:
                return [h for h in all_history if h.get('user_id') == current_user.id]
            return []
    except:
        return []

def save_history(history):
    all_history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                all_history = json.load(f)
        except:
            pass
    
    user_id = current_user.id if current_user.is_authenticated else None
    rest_history = [h for h in all_history if h.get('user_id') != user_id]
    
    for h in history:
        h['user_id'] = user_id
        
    all_history = history + rest_history
    
    with open(HISTORY_FILE, 'w') as f:
        json.dump(all_history, f, indent=4)

def add_to_history(filename, excel_filename):
    history = load_history()
    entry = {
        'id': str(uuid.uuid4()),
        'user_id': current_user.id,
        'filename': filename,
        'excel_filename': excel_filename,
        'source_excel': excel_filename,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    history.insert(0, entry)
    save_history(history)
    return entry

def delete_from_history(entry_id):
    all_history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                all_history = json.load(f)
        except:
            pass
            
    entry = next((item for item in all_history if item['id'] == entry_id and item.get('user_id') == current_user.id), None)
    
    if entry:
        excel_path = os.path.join(app.config['UPLOAD_FOLDER'], entry['excel_filename'])
        if os.path.exists(excel_path):
            os.remove(excel_path)
            
        # Also remove cached stats JSON
        stats_path = excel_path.replace('.xlsx', '.json')
        if os.path.exists(stats_path):
            os.remove(stats_path)
            
        # Remove mapped excel if it exists
        if 'mapped_excel_filename' in entry and entry['mapped_excel_filename']:
            mapped_excel_path = os.path.join(app.config['UPLOAD_FOLDER'], entry['mapped_excel_filename'])
            if os.path.exists(mapped_excel_path):
                os.remove(mapped_excel_path)
            mapped_stats_path = mapped_excel_path.replace('.xlsx', '.json')
            if os.path.exists(mapped_stats_path):
                os.remove(mapped_stats_path)
            
        all_history = [item for item in all_history if item['id'] != entry_id]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(all_history, f, indent=4)

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.password and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password')
            
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name')
        password = request.form.get('password')
        
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Email already registered')
            return redirect(url_for('signup'))
            
        new_user = User(email=email, name=name, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('dashboard'))
        
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    history = load_history()
    return render_template('index.html', history=history, user=current_user, active_page='converter')
@app.route('/calculator')
@login_required
def calculator():
    return render_template('calculator.html', user=current_user, active_page='gpa')

def generate_excel_report(df, stats, exam_title, excel_path, college_name="KTU Result Analysis", include_perf=True):
    latest_year = df['Year'].max()
    with pd.ExcelWriter(excel_path, engine='xlsxwriter', engine_kwargs={'options': {'nan_inf_to_errors': True}}) as writer:
        # Allow NaN SGPA values to remain (for passed students with no credits)
        workbook = writer.book
        
        # --- Professional Styles ---
        fmt_header_main = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#9333EA', 'align': 'center', 'valign': 'vcenter', 'font_size': 14, 'border': 1
        })
        fmt_header_college = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#22C55E', 'align': 'center', 'valign': 'vcenter', 'font_size': 11, 'border': 1
        })
        fmt_header_exam = workbook.add_format({
            'bold': True, 'font_color': 'black', 'bg_color': '#FACC15', 'align': 'center', 'valign': 'vcenter', 'font_size': 11, 'border': 1
        })
        fmt_header_sub = workbook.add_format({
            'bold': True, 'bg_color': '#10B981', 'align': 'center', 'valign': 'vcenter', 'font_size': 11, 'border': 1
        })
        fmt_section_orange = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#F97316', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10
        })
        fmt_table_header_blue = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#1E3A8A', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True, 'font_size': 9
        })
        fmt_border = workbook.add_format({'border': 1, 'align': 'center'})
        fmt_no_border = workbook.add_format({'border': 0, 'align': 'center'})
        fmt_sgpa_no_border = workbook.add_format({'border': 0, 'align': 'center', 'num_format': '0.00'})
        fmt_cond_border = workbook.add_format({'border': 1, 'align': 'center'})
        fmt_cond_sgpa = workbook.add_format({'border': 1, 'align': 'center', 'num_format': '0.00'})
        fmt_percent = workbook.add_format({'border': 1, 'align': 'center', 'num_format': '00.0', 'bold': True})
        fmt_total_row = workbook.add_format({'border': 1, 'align': 'center', 'bold': True, 'bg_color': '#E5E7EB'})
        fmt_total_row_percent = workbook.add_format({'border': 1, 'align': 'center', 'bold': True, 'bg_color': '#E5E7EB', 'num_format': '00.0'})
        fmt_rank_header = workbook.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#1E3A8A', 'border': 1, 'align': 'center'
        })
        fmt_stats_bar = workbook.add_format({
            'bold': True, 'bg_color': '#FEF3C7', 'align': 'center', 'valign': 'vcenter', 'font_size': 9, 'border': 1
        })
        fmt_note = workbook.add_format({
            'italic': True, 'font_color': '#EF4444', 'font_size': 9, 'align': 'left'
        })
        fmt_alt_row_1 = workbook.add_format({'bg_color': '#EFF6FF', 'border': 1, 'align': 'center'}) # Light Blue
        fmt_alt_row_2 = workbook.add_format({'bg_color': '#ECFDF5', 'border': 1, 'align': 'center'}) # Light Green
        fmt_value_gray = workbook.add_format({'bg_color': '#F3F4F6', 'border': 1, 'align': 'center', 'bold': True})
        fmt_percent_gray = workbook.add_format({'bg_color': '#F3F4F6', 'border': 1, 'align': 'center', 'bold': True, 'num_format': '00.0'})
        fmt_pass_cell  = workbook.add_format({'bg_color': '#E2EFDA', 'border': 1, 'align': 'center', 'bold': True})  # Light Green tint
        fmt_fail_cell  = workbook.add_format({'bg_color': '#FCE4D6', 'border': 1, 'align': 'center', 'bold': True})  # Light Red/Orange tint

        # SGPA Heatmap Font Formats
        fmt_sgpa_top    = workbook.add_format({'bold': True, 'font_color': '#00B050', 'border': 1, 'align': 'center', 'num_format': '0.00'}) # Strong Green
        fmt_sgpa_high   = workbook.add_format({'bold': True, 'font_color': '#70AD47', 'border': 1, 'align': 'center', 'num_format': '0.00'}) # Light Green
        fmt_sgpa_mid    = workbook.add_format({'bold': True, 'font_color': '#FFC000', 'border': 1, 'align': 'center', 'num_format': '0.00'}) # Amber/Yellow
        fmt_sgpa_low    = workbook.add_format({'bold': True, 'font_color': '#FF0000', 'border': 1, 'align': 'center', 'num_format': '0.00'}) # Light Red

        # --- Dashboard Component Styles ---
        fmt_card_title = workbook.add_format({'bold': True, 'font_size': 10, 'align': 'center', 'font_color': '#475569', 'bg_color': '#F8FAFC'})
        fmt_card_val_blue = workbook.add_format({'bold': True, 'font_size': 20, 'align': 'center', 'font_color': '#002060', 'bg_color': '#F8FAFC'}) # Deep Navy
        fmt_card_val_green = workbook.add_format({'bold': True, 'font_size': 20, 'align': 'center', 'font_color': '#00B050', 'bg_color': '#F8FAFC'}) # Emerald
        fmt_card_val_red = workbook.add_format({'bold': True, 'font_size': 20, 'align': 'center', 'font_color': '#C00000', 'bg_color': '#F8FAFC'}) # Crimson
        fmt_card_perc = workbook.add_format({'bold': True, 'font_size': 18, 'align': 'center', 'font_color': '#4B5563', 'bg_color': '#F8FAFC', 'num_format': '0.0"%"'})
        fmt_dropdown_label = workbook.add_format({'bold': True, 'align': 'right', 'valign': 'vcenter', 'font_size': 11})
        fmt_dropdown_box = workbook.add_format({'bg_color': '#FFFFE0', 'border': 2, 'border_color': '#FACC15', 'align': 'center', 'valign': 'vcenter', 'bold': True})
        
        # --- Create Worksheets in Desired Physical Order ---
        all_results_sheet = workbook.add_worksheet('All Results')
        all_results_sheet.hide() # Keep hidden as requested
        
        # Check if student name exists
        has_names = 'Student Name' in df.columns
        all_results_cols = ['Register No']
        if has_names:
            all_results_cols.append('Student Name')
        all_results_cols.extend(['Year', 'Dept', 'Scheme', 'Subject', 'Subject Name', 'Grade', 'SGPA'])
        
        for i, col in enumerate(all_results_cols):
            all_results_sheet.write(0, i, col, fmt_table_header_blue)
        
        for i, row in df[all_results_cols].iterrows():
            for j, val in enumerate(row):
                # Explicitly handle NaN (for passed student with no credits) to write as blank
                write_val = val if not pd.isna(val) else ""
                all_results_sheet.write(i + 1, j, write_val, fmt_border)


        summary_sheet = workbook.add_worksheet('OVERALL SUMMARY')
        summary_sheet.activate() # Focused on open
        
        summary_sheet.merge_range('A1:G1', 'KTU RESULT ANALYZER - OVERALL SUMMARY REPORT', fmt_header_main)
        summary_sheet.merge_range('A2:G2', college_name, fmt_header_college)
        summary_sheet.merge_range('A3:G3', exam_title, fmt_header_exam)
        dept_sheets = {}
        for dept in stats['departments']:
            dept_sheets[dept] = workbook.add_worksheet(dept[:31])
        
        students_data_sheet = workbook.add_worksheet('_STUDENTS_')
        students_data_sheet.hide()

        data_sheet = workbook.add_worksheet('_DATA_')
        data_sheet.hide()
        students_row_idx = 1
        data_sheet.write(0, 0, 'Dept_Subject_Key')
        data_sheet.write(0, 1, 'Appeared')
        data_sheet.write(0, 2, 'Passed')
        data_sheet.write(0, 3, 'Failed')
        data_sheet.write(0, 4, 'Pass_P')
        data_sheet.write(0, 5, 'Fail_P')
        # Dynamic Grades
        grade_headers = ['S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'PASS', 'F', 'FE', 'Absent', 'Withheld']
        
        for i, h in enumerate(grade_headers):
            data_sheet.write(0, 6 + i, h)
            
        data_row_idx = 1
        dept_subjects_map = {} # dept -> [list of subjects]

        for dept in stats['departments']:
            dept_subjects_map[dept] = ["Department"]
            dept_info = stats['dept_summary'][dept]
            dept_clean = str(dept).strip().upper()
            data_sheet.write(data_row_idx, 0, f"{dept_clean}_DEPARTMENT")
            data_sheet.write(data_row_idx, 1, dept_info.get('regular', 0))
            data_sheet.write(data_row_idx, 2, dept_info.get('reg_pass', 0))
            data_sheet.write(data_row_idx, 3, dept_info.get('reg_fail', 0))
            d_pass_p = (dept_info['reg_pass']/dept_info['regular']*100) if dept_info.get('regular', 0) > 0 else 0
            data_sheet.write(data_row_idx, 4, d_pass_p)
            data_sheet.write(data_row_idx, 5, 100 - d_pass_p)
            
            d_dist = dept_info.get('grade_dist', {})
            for i, g in enumerate(grade_headers):
                data_sheet.write(data_row_idx, 6 + i, d_dist.get(g, 0))
            
            data_row_idx += 1

            dept_sub_agg_data = {}
            if dept in stats['dept_sub_stats']:
                for y, subs in stats['dept_sub_stats'][dept].items():
                    for sub, yr_data in subs.items():
                        if sub not in dept_sub_agg_data:
                            dept_sub_agg_data[sub] = {
                                'total': 0, 'pass': 0, 'fail': 0, 'grade_dist': {},
                                'student_lists': {'topper_8_above': [], 'above_7_5': [], 'fail_detailed': []}
                            }
                        
                        ad = dept_sub_agg_data[sub]
                        ad['total'] += yr_data['total']
                        ad['pass'] += yr_data['pass']
                        ad['fail'] += yr_data['fail']
                        for gd, count in yr_data.get('grade_dist', {}).items():
                            ad['grade_dist'][gd] = ad['grade_dist'].get(gd, 0) + count
                        
                        sl = yr_data.get('student_lists', {})
                        ad['student_lists']['topper_8_above'].extend(sl.get('topper_8_above', []))
                        ad['student_lists']['above_7_5'].extend(sl.get('above_7_5', []))
                        ad['student_lists']['fail_detailed'].extend(sl.get('fail_detailed', []))

            for sub in sorted(dept_sub_agg_data.keys()):
                dept_subjects_map[dept].append(sub)
                yr_data = dept_sub_agg_data[sub]
                s_total = yr_data['total']
                s_pass = yr_data['pass']
                s_fail = yr_data['fail']
                
                sub_clean = str(sub).strip().upper()
                key = f"{dept_clean}_{sub_clean}"
                data_sheet.write(data_row_idx, 0, key)
                data_sheet.write(data_row_idx, 1, s_total)
                data_sheet.write(data_row_idx, 2, s_pass)
                data_sheet.write(data_row_idx, 3, s_fail)
                s_pass_p = (s_pass / s_total * 100) if s_total > 0 else 0
                data_sheet.write(data_row_idx, 4, s_pass_p)
                data_sheet.write(data_row_idx, 5, 100 - s_pass_p)
                
                s_grade_dist = yr_data.get('grade_dist', {})
                for i, g in enumerate(grade_headers):
                    data_sheet.write(data_row_idx, 6 + i, s_grade_dist.get(g, 0))
                
                sub_lists = yr_data.get('student_lists', {})
                for item in sub_lists.get('topper_8_above', []):
                    r, s = item[0], item[1]
                    students_data_sheet.write_row(students_row_idx, 0, [key, 'Topper', r, s])
                    students_row_idx += 1
                for item in sub_lists.get('above_7_5', []):
                    r, s = item[0], item[1]
                    students_data_sheet.write_row(students_row_idx, 0, [key, 'Above75', r, s])
                    students_row_idx += 1
                for item in sub_lists.get('fail_detailed', []):
                    r = item[0]
                    students_data_sheet.write_row(students_row_idx, 0, [key, 'Failed', r, '-'])
                    students_row_idx += 1
                    
                data_row_idx += 1


        # Build a robust reg_df that includes the "current batch" for EACH department
        reg_df_list = []
        for dpt in df['Dept'].unique():
            d_df = df[df['Dept'] == dpt]
            if not d_df.empty:
                d_main_year = d_df['Year'].value_counts().idxmax()
                # Include main batch AND lateral entry students
                d_current_years = [y for y in d_df['Year'].unique() if y >= d_main_year]
                reg_df_list.append(d_df[d_df['Year'].isin(d_current_years)])
        
        reg_df = pd.concat(reg_df_list) if reg_df_list else df.copy()
        
        total_reg_students = reg_df['Register No'].nunique()
        
        global_passed_reg = 0
        if total_reg_students > 0:
            reg_df['is_fail'] = reg_df['Grade'].isin(['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I'])
            failed_students = reg_df.groupby('Register No')['is_fail'].any()
            global_passed_reg = int(total_reg_students - failed_students.sum())
        
        summary_sheet.merge_range('A5:E5', 'OVERALL STATISTICS - REGULAR STUDENTS ONLY', fmt_section_orange)
        overall_pass_perc = (global_passed_reg / total_reg_students * 100) if total_reg_students > 0 else 0
        overall_stat_headers = ['Total Reg Students', 'Total Passed', 'Total Failed', 'Overall Pass %', 'Overall Fail %']
        for ci, h in enumerate(overall_stat_headers):
            summary_sheet.write(5, ci, h, fmt_table_header_blue)
        summary_sheet.write(6, 0, total_reg_students, fmt_alt_row_1)
        summary_sheet.write(6, 1, global_passed_reg, fmt_pass_cell)
        summary_sheet.write(6, 2, int(total_reg_students - global_passed_reg), fmt_fail_cell)
        
        fmt_pct_alt = workbook.add_format({'num_format': '00.0', 'border': 1, 'align': 'center', 'bg_color': '#EFF6FF', 'bold': True})
        summary_sheet.write(6, 3, overall_pass_perc, fmt_pct_alt)
        summary_sheet.write(6, 4, 100 - overall_pass_perc, fmt_pct_alt)
        
        summary_sheet.merge_range('A11:F11', 'DEPARTMENT-WISE PERFORMANCE ANALYSIS', fmt_section_orange)
        for i, h in enumerate(['Department Name', 'Total Regular Students', 'Total Pass', 'Total Fail', 'Pass %', 'Fail %']):
            summary_sheet.write(11, i, h, fmt_table_header_blue)
        
        row_idx = 12
        for i, dept in enumerate(stats.get('departments', [])):
            dept_stats = stats['dept_summary'].get(dept, {})
            pass_perc = (dept_stats.get('reg_pass', 0) / dept_stats.get('regular', 1) * 100)
            fmt_row = fmt_alt_row_1 if i % 2 == 0 else fmt_alt_row_2
            fmt_pct = workbook.add_format({'num_format': '00.0', 'border': 1, 'align': 'center', 'bg_color': fmt_row.bg_color})
            
            summary_sheet.write(row_idx, 0, dept, fmt_row)
            summary_sheet.write(row_idx, 1, dept_stats.get('regular', 0), fmt_row)
            summary_sheet.write(row_idx, 2, dept_stats.get('reg_pass', 0), fmt_pass_cell)
            summary_sheet.write(row_idx, 3, dept_stats.get('regular', 0) - dept_stats.get('reg_pass', 0), fmt_fail_cell)
            summary_sheet.write(row_idx, 4, pass_perc, fmt_pct)
            summary_sheet.write(row_idx, 5, 100 - pass_perc, fmt_pct)
            row_idx += 1
        
        subject_stats = []
        if not reg_df.empty:
            sub_group = reg_df.groupby(['Dept', 'Subject'])['Grade'].agg(
                total='count',
                fail=lambda x: x.isin(['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I']).sum()
            ).reset_index()
            sub_group['pass'] = sub_group['total'] - sub_group['fail']
            sub_group['pass_p'] = (sub_group['pass'] / sub_group['total'] * 100)
            for _, row in sub_group.iterrows():
                # Only include subjects with at least 10 students for Top/Bottom 5 ranking 
                # This ensures we report on the current batch batch, not single-student outliers/backlogs
                if row['total'] >= 10:
                    subject_stats.append({
                        'code': row['Subject'], 'dept': row['Dept'], 'pass_p': row['pass_p'], 
                        'total': int(row['total']), 'pass': int(row['pass']), 'fail': int(row['fail'])
                    })
        subject_stats.sort(key=lambda x: (x['pass_p'], x['total']), reverse=True)
        top_5 = subject_stats[:5]
        bottom_5 = sorted(subject_stats, key=lambda x: (x['pass_p'], x['total']))[:5]
        
        # Red font for Pass % < 40 on the entire summary sheet
        fmt_red_pct = workbook.add_format({'bold': True, 'font_color': '#C00000', 'border': 1, 'align': 'center', 'num_format': '00.0'})

        for title, items in [('TOP 5 PERFORMING SUBJECTS', top_5), ('BOTTOM 5 PERFORMING SUBJECTS (NEEDS ATTENTION)', bottom_5)]:
            row_idx += 2
            summary_sheet.merge_range(row_idx, 0, row_idx, 7, title, fmt_section_orange)
            row_idx += 1
            for i, h in enumerate(['Rank', 'Subject Code', 'Department', 'Pass %', 'Fail %', 'Total Students', 'Pass', 'Fail']):
                summary_sheet.write(row_idx, i, h, fmt_rank_header)
            row_idx += 1
            
            table_start_row = row_idx
            for r_i, item in enumerate(items):
                fmt_r = fmt_alt_row_1 if r_i % 2 == 0 else fmt_alt_row_2
                fmt_p = workbook.add_format({'num_format': '00.0', 'border': 1, 'align': 'center', 'bg_color': fmt_r.bg_color, 'bold': True})
                
                summary_sheet.write(row_idx, 0, r_i + 1, fmt_r)
                summary_sheet.write(row_idx, 1, item['code'], fmt_r)
                summary_sheet.write(row_idx, 2, item['dept'], fmt_r)
                summary_sheet.write(row_idx, 3, item['pass_p'], fmt_p)
                summary_sheet.write(row_idx, 4, 100 - item['pass_p'], fmt_p)
                summary_sheet.write(row_idx, 5, item['total'], fmt_r)
                summary_sheet.write(row_idx, 6, item['pass'], fmt_pass_cell)
                summary_sheet.write(row_idx, 7, item['fail'], fmt_fail_cell)
                row_idx += 1
            
            table_end_row = row_idx - 1
            if items:
                # Apply red font conditional formatting ONLY to the actual data rows of this table
                summary_sheet.conditional_format(table_start_row, 3, table_end_row, 3, {
                    'type': 'cell', 'criteria': '<', 'value': 40, 'format': fmt_red_pct
                })

        summary_sheet.set_column('A:B', 18)
        summary_sheet.set_column('C:H', 15)
        
        # Dept-wise Pass % column (col E = index 4), rows 12 to 12+len(depts)
        dept_end_row = 11 + len(stats.get('departments', []))
        summary_sheet.conditional_format(f'E13:E{dept_end_row + 1}', {
            'type': 'cell', 'criteria': '<', 'value': 40, 'format': fmt_red_pct
        })

        
        for dept in stats['departments']:
            dept_df = df[df['Dept'] == dept]
            if dept_df.empty: continue
            
            # Identify main year/current batch for this department early for all sections
            filtered_dept_df = dept_df.copy()
            if not filtered_dept_df.empty:
                main_year = filtered_dept_df['Year'].value_counts().idxmax()
                current_years = [y for y in filtered_dept_df['Year'].unique() if y >= main_year]
            else:
                main_year = "Unknown"
                current_years = []
            
            # Pivot with name if available
            pivot_index = ['Register No']
            if has_names:
                pivot_index.append('Student Name')
            
            pivot_df = dept_df.pivot_table(index=pivot_index, columns='Subject', values='Grade', aggfunc='first').fillna('-')
            filtered_dept_df = dept_df.copy()
            arrears_series = filtered_dept_df[filtered_dept_df['Grade'].isin(['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I'])].groupby('Register No').size()
            pivot_df['Arrears_Count'] = arrears_series.reindex(pivot_df.index.get_level_values('Register No'), fill_value=0).astype(int)
            sgpa_series = filtered_dept_df.groupby('Register No')['SGPA'].first()
            pivot_df['SGPA'] = sgpa_series.reindex(pivot_df.index, level='Register No')
            
            def get_adm_year(reg):
                m = re.search(r'\d{2}', str(reg))
                return f"20{m.group()}" if m else "Unknown"
            
            pivot_df['AdmYear'] = [get_adm_year(r[0] if isinstance(r, tuple) else r) for r in pivot_df.index]
            years = sorted(pivot_df['AdmYear'].unique())
            sheet = dept_sheets[dept]
            sheet_name = dept[:31]
            
            sheet.set_column(0, 0, 15) # Register No
            if has_names:
                sheet.set_column(1, 1, 45) # Student Name / Subject Name
                name_offset = 1
            else:
                sheet.set_column(1, 1, 45) # Subject Name
                name_offset = 0
                
            max_display_cols = 16 + name_offset
            sheet.merge_range(0, 0, 0, max_display_cols, 'KTU RESULT ANALYZER', fmt_header_main)
            sheet.merge_range(1, 0, 1, max_display_cols, college_name, fmt_header_college)
            sheet.merge_range(2, 0, 2, max_display_cols, exam_title, fmt_header_exam)
            sheet.merge_range(3, 0, 3, max_display_cols, f"Department: {dept}", fmt_header_sub)
            
            dept_stats = stats['dept_summary'][dept]
            stats_str = f"📊 Overall Stats: {dept_stats['count']} Students | {dept_stats['regular']} Regular | {dept_stats['backlog']} Backlog"
            sheet.merge_range(4, 0, 4, max_display_cols, stats_str, fmt_stats_bar)
            
            # Dashboard at the TOP
            curr_row = 6
            # Dashboard Title at A to L (0 to 11)
            sheet.merge_range(curr_row, 0, curr_row, 11, "SUBJECT ANALYTICS DASHBOARD", fmt_section_orange)
            curr_row += 1
            # Dropdown will be at B8 (Excel) / Row 7, Col 1
            sheet.write(curr_row, 0, "Select Subject:", fmt_dropdown_label)
            subj_list = dept_subjects_map.get(dept, ["Department"])
            sheet.data_validation(curr_row, 1, curr_row, 1, {'validate': 'list', 'source': subj_list})
            sheet.write(curr_row, 1, "Department", fmt_dropdown_box)
            
            # Gap of 3 empty rows (7, 8, 9)
            # Move cards closer to dropdown (reduce from += 4 to += 2)
            curr_row += 2 
            # Metrics Cards from B to L (1 to 11)
            card_labels = ["Appeared", "Passed", "Failed", "Pass Rate", "Fail Rate"]
            card_formats = [fmt_card_val_blue, fmt_card_val_green, fmt_card_val_red, fmt_card_perc, fmt_card_perc]
            # Precise columns: Card 1 (1-2), Card 2 (3-5), Card 3 (6-7), Card 4 (8-9), Card 5 (10-11)
            ranges = [(1, 2), (3, 5), (6, 7), (8, 9), (10, 11)]
            for i, (c1, c2) in enumerate(ranges):
                sheet.merge_range(curr_row, c1, curr_row, c2, card_labels[i], fmt_card_title)
                # Dropdown is at $B$8 (Row 7)
                vlookup_formula = f'=IFERROR(VLOOKUP("{dept.upper()}_" & UPPER($B$8), _DATA_!$A$2:$AZ${data_row_idx}, {i+2}, FALSE), 0)'
                sheet.merge_range(curr_row + 1, c1, curr_row + 2, c2, vlookup_formula, card_formats[i])

            # Hidden Bridges for Chart Data (Fixed Location)
            sheet.write(500, 51, f'="{dept.upper()}_" & UPPER($B$8)')
            G_BRIDGE, P_BRIDGE, COL_AZ, COL_BA = 505, 520, 51, 52
            for i, g in enumerate(grade_headers):
                sheet.write(G_BRIDGE+i, COL_AZ, f'="{g} - " & TEXT($BA${G_BRIDGE+i+1}/MAX($BA${P_BRIDGE+1}, 1), "0%")')
                sheet.write(G_BRIDGE+i, COL_BA, f'=IFERROR(VLOOKUP($AZ$501, _DATA_!$A$2:$AZ${data_row_idx}, {7+i}, FALSE), 0)')
            for i, label in enumerate(["Appeared", "Passed", "Failed"]):
                sheet.write(P_BRIDGE+i, COL_AZ, label)
                sheet.write(P_BRIDGE+i, COL_BA, f'=IFERROR(VLOOKUP($AZ$501, _DATA_!$A$2:$T${data_row_idx}, {2+i}, FALSE), 0)')

            grade_chart = workbook.add_chart({'type': 'doughnut'})
            grade_chart.add_series({
                'name': 'Grade Dist',
                'categories': [sheet_name, G_BRIDGE, COL_AZ, G_BRIDGE+len(grade_headers)-1, COL_AZ],
                'values':     [sheet_name, G_BRIDGE, COL_BA, G_BRIDGE+len(grade_headers)-1, COL_BA],
            })
            grade_chart.set_legend({'position': 'bottom'})
            
            perf_chart = workbook.add_chart({'type': 'column'})
            perf_chart.add_series({
                'categories': [sheet_name, P_BRIDGE, COL_AZ, P_BRIDGE+2, COL_AZ],
                'values':     [sheet_name, P_BRIDGE, COL_BA, P_BRIDGE+2, COL_BA],
            })
            perf_chart.set_legend({'none': True})

            # Insert charts side-by-side with 1-row gap below cards (curr_row + 4)
            # Move Grade chart to Column B (1) and Performance chart to Column G (6)
            sheet.insert_chart(curr_row + 4, 1, grade_chart, {'x_scale': 1.0, 'y_scale': 1.1})
            sheet.insert_chart(curr_row + 4, 6, perf_chart, {'x_scale': 1.2, 'y_scale': 1.1})

            curr_row += 22  # Charts cover ~15 rows + 1 gap above + 3 row gap below
            for year in years:
                year_df = pivot_df[pivot_df['AdmYear'] == year].drop(columns=['AdmYear'])
                active_cols = [col for col in year_df.columns if (year_df[col] != '-').any() or col == 'Arrears_Count' or col == 'SGPA']
                batch_df = year_df[active_cols]
                batch_end_col = len(active_cols) + name_offset
                
                sheet.merge_range(curr_row, 0, curr_row, batch_end_col, f"BATCH - {year}", fmt_section_orange)
                curr_row += 1
                sheet.write(curr_row, 0, 'Register No', fmt_table_header_blue)
                if has_names: sheet.write(curr_row, 1, 'Student Name', fmt_table_header_blue)
                for i, col in enumerate(active_cols):
                    header_val = col
                    if col == 'Arrears_Count':
                        header_val = 'Arrears'
                    elif col in stats.get('subject_names', {}):
                        header_val = col
                    sheet.write(curr_row, i + 1 + name_offset, header_val, fmt_table_header_blue)
                    # Set a reasonable width for subject columns to allow wrapping
                    if col != 'Arrears_Count' and col != 'SGPA':
                        sheet.set_column(i + 1 + name_offset, i + 1 + name_offset, 15)
                curr_row += 1
                
                # Sort batch by Register No
                batch_df_sorted = batch_df.sort_index(level='Register No')
                for r_idx, (idx, row_data) in enumerate(batch_df_sorted.iterrows()):
                    fmt_c = fmt_alt_row_1 if r_idx % 2 == 0 else fmt_alt_row_2
                    fmt_s = workbook.add_format({'num_format': '0.00', 'border': 1, 'align': 'center', 'bg_color': fmt_c.bg_color})
                    
                    reg = idx[0] if has_names else idx
                    sheet.write(curr_row, 0, reg, fmt_c)
                    if has_names: sheet.write(curr_row, 1, idx[1], fmt_c)
                    
                    for c_idx, val in enumerate(row_data):
                        if active_cols[c_idx] == 'SGPA':
                            if pd.isna(val): # Passed but no credits found in this PDF
                                sheet.write(curr_row, c_idx + 1 + name_offset, "", fmt_c)
                            else: # Fail-category (0.0) or Normal SGPA (float)
                                sheet.write(curr_row, c_idx + 1 + name_offset, val, fmt_s)
                        else:
                            sheet.write(curr_row, c_idx + 1 + name_offset, val, fmt_c)
                    curr_row += 1
                
                # Apply red font conditional formatting for fail grades on the batch data range
                batch_data_first_row  = curr_row - (len(batch_df_sorted))
                batch_data_last_row   = curr_row - 1
                fail_grades = ['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I']
                fmt_red_font = workbook.add_format({'bold': True, 'font_color': '#C00000', 'border': 1, 'align': 'center'})
                for fg in fail_grades:
                    sheet.conditional_format(batch_data_first_row, 0, batch_data_last_row, batch_end_col, {
                        'type': 'text',
                        'criteria': 'containing',
                        'value': fg,
                        'format': fmt_red_font
                    })

                # SGPA Heatmap (Comparative Font Colors)
                sgpa_col_idx = -1
                for ci, c_name in enumerate(active_cols):
                    if c_name == 'SGPA':
                        sgpa_col_idx = ci + 1 + name_offset
                        break
                
                if sgpa_col_idx != -1:
                    # Rule 1: Top 1 Score (Strong Green)
                    sheet.conditional_format(batch_data_first_row, sgpa_col_idx, batch_data_last_row, sgpa_col_idx, {
                        'type': 'top', 'value': 1, 'format': fmt_sgpa_top
                    })
                    # Rule 2: >= 8.0 (Light Green)
                    sheet.conditional_format(batch_data_first_row, sgpa_col_idx, batch_data_last_row, sgpa_col_idx, {
                        'type': 'cell', 'criteria': '>=', 'value': 8.0, 'format': fmt_sgpa_high
                    })
                    # Rule 3: 7.5 to 7.99 (Amber)
                    sheet.conditional_format(batch_data_first_row, sgpa_col_idx, batch_data_last_row, sgpa_col_idx, {
                        'type': 'cell', 'criteria': 'between', 'minimum': 7.5, 'maximum': 7.99, 'format': fmt_sgpa_mid
                    })
                    # Rule 4: < 7.5 (Light Red)
                    sheet.conditional_format(batch_data_first_row, sgpa_col_idx, batch_data_last_row, sgpa_col_idx, {
                        'type': 'cell', 'criteria': '<', 'value': 7.5, 'format': fmt_sgpa_low
                    })

                curr_row += 4      # 3-row gap after each batch table
            
            # PERFORMANCE ANALYSIS (Current Year Only) above Subject Analysis
            sheet.merge_range(curr_row, 0, curr_row, 5, f"DEPARTMENT PERFORMANCE ANALYSIS (BATCH {main_year})", fmt_section_orange)
            headers_perf = ["Batch", "Total Students", "Total Pass", "Total Fail", "Pass %", "Fail %"]
            for i, h in enumerate(headers_perf):
                sheet.write(curr_row + 1, i, h, fmt_table_header_blue)
            
            y_df = filtered_dept_df[filtered_dept_df['Year'] == main_year]
            y_total = y_df['Register No'].nunique()
            y_pass = 0
            if y_total > 0:
                y_failed = y_df.groupby('Register No')['Grade'].apply(lambda x: x.isin(['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I']).any()).sum()
                y_pass = int(y_total - y_failed)
            
            y_pass_p = (y_pass / y_total * 100) if y_total > 0 else 0
            fmt_pct_perf = workbook.add_format({'num_format': '0.0', 'border': 1, 'bg_color': '#EFF6FF', 'align': 'center', 'bold': True})
            sheet.write(curr_row + 2, 0, main_year, fmt_alt_row_1)
            sheet.write(curr_row + 2, 1, y_total, fmt_alt_row_1)
            sheet.write(curr_row + 2, 2, y_pass, fmt_alt_row_1)
            sheet.write(curr_row + 2, 3, y_total - y_pass, fmt_alt_row_1)
            sheet.write(curr_row + 2, 4, y_pass_p, fmt_pct_perf)
            sheet.write(curr_row + 2, 5, 100 - y_pass_p, fmt_pct_perf)
            
            # Red font if Pass % < 40 on Dept Performance Analysis row
            fmt_red_pct_dept = workbook.add_format({'bold': True, 'font_color': '#C00000', 'border': 1, 'align': 'center', 'num_format': '0.0'})
            sheet.conditional_format(curr_row + 2, 4, curr_row + 2, 4, {
                'type': 'cell', 'criteria': '<', 'value': 40, 'format': fmt_red_pct_dept
            })
            
            curr_row += 6 # Summary table (3 rows) + 3-row gap below
            sheet.merge_range(curr_row, 0, curr_row, 18, f"SUBJECT-WISE ANALYSIS (BATCH - {main_year})", fmt_section_orange)
            sub_headers = ['SubCode', 'Subject Name', 'Pass%', 'Fail%', 'Pass', 'Fail', 'S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'F', 'FE', 'Absent', 'Withheld']
            for i, h in enumerate(sub_headers):
                sheet.write(curr_row + 1, i, h, fmt_table_header_blue)
            
            row_idx = curr_row + 2
            dept_sub_agg = {}
            if dept in stats['dept_sub_stats']:
                for y in current_years:
                    if y in stats['dept_sub_stats'][dept]:
                        for s_code, s_data in stats['dept_sub_stats'][dept][y].items():
                            if s_code not in dept_sub_agg:
                                dept_sub_agg[s_code] = {'total': 0, 'pass': 0, 'fail': 0, 'grade_dist': {}}
                            dept_sub_agg[s_code]['total'] += s_data['total']
                            dept_sub_agg[s_code]['pass'] += s_data['pass']
                            dept_sub_agg[s_code]['fail'] += s_data['fail']
                            for gd, count in s_data.get('grade_dist', {}).items():
                                dept_sub_agg[s_code]['grade_dist'][gd] = dept_sub_agg[s_code]['grade_dist'].get(gd, 0) + count

            for s_i, sub_code in enumerate(sorted(dept_sub_agg.keys())):
                s_data = dept_sub_agg[sub_code]
                fmt_row = fmt_alt_row_1 if s_i % 2 == 0 else fmt_alt_row_2
                
                s_pass_p = (s_data['pass'] / s_data['total'] * 100) if s_data['total'] > 0 else 0
                
                sheet.write(row_idx, 0, sub_code, fmt_row)
                sheet.write(row_idx, 1, stats.get('subject_names', {}).get(sub_code, sub_code), fmt_row)
                
                fmt_pct = workbook.add_format({'num_format': '0.0', 'border': 1, 'bg_color': fmt_row.bg_color, 'align': 'center'})
                sheet.write(row_idx, 2, s_pass_p, fmt_pct)
                sheet.write(row_idx, 3, 100 - s_pass_p, fmt_pct)
                sheet.write(row_idx, 4, s_data['pass'], fmt_row)
                sheet.write(row_idx, 5, s_data['fail'], fmt_row)
                
                dist = s_data.get('grade_dist', {})
                # Grade columns start at index 6: S, A+, A, B+, B, C+, C, D, P, F, FE, Absent, Withheld
                grades_to_write = ['S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'F', 'FE', 'ABSENT', 'WITHHELD']
                for gi, g_code in enumerate(grades_to_write):
                    # For statistical mapping, match the uppercase normalization
                    count = dist.get(g_code, 0)
                    sheet.write(row_idx, 6 + gi, count, fmt_row)
                
                row_idx += 1

            # Red font on Subject-wise Pass% column (col C = index 2) if < 40
            if dept_sub_agg:
                subj_data_start = curr_row + 2
                subj_data_end   = row_idx - 1
                fmt_red_subj_pct = workbook.add_format({'bold': True, 'font_color': '#C00000', 'border': 1, 'align': 'center', 'num_format': '0.0'})
                sheet.conditional_format(subj_data_start, 2, subj_data_end, 2, {
                    'type': 'cell', 'criteria': '<', 'value': 40, 'format': fmt_red_subj_pct
                })

        if include_perf:
            # --- Subject Performance Sheet (Moved to Last) ---
            subject_perf_sheet = workbook.add_worksheet('Subject Performance')
            subject_perf_sheet.set_column(0, 0, 15) # Reg No
            subject_perf_sheet.set_column(1, 1, 30) # Name
            subject_perf_sheet.set_column(2, 2, 10) # Grade
            subject_perf_sheet.set_column(3, 3, 5)  # Spacer
            subject_perf_sheet.set_column(4, 4, 15) # Reg No
            subject_perf_sheet.set_column(5, 5, 30) # Name
            subject_perf_sheet.set_column(6, 6, 10) # Grade

            subject_perf_sheet.merge_range('A1:G1', 'SUBJECT PERFORMANCE ANALYSIS', fmt_header_main)
            subject_perf_sheet.merge_range('B3:C3', 'SELECT SUBJECT CODE:', fmt_dropdown_label)
            # Only include subjects with at least 10 students in the dropdown for better readability
            all_subjects = sorted([s['code'] for s in subject_stats if s['total'] >= 10])
            if not all_subjects:
                all_subjects = sorted(stats['subjects']) # Fallback if everything is filtered
            subject_perf_sheet.data_validation('D3:E3', {'validate': 'list', 'source': all_subjects})
            if all_subjects:
                subject_perf_sheet.merge_range('D3:E3', all_subjects[0], fmt_dropdown_box)
            
            # Determine correct column letters based on has_names
            # all_results_cols layout:
            #   with names:    A=RegNo, B=Name, C=Year, D=Dept, E=Scheme, F=Subject, G=SubjectName, H=Grade
            #   without names: A=RegNo, B=Year,  C=Dept, D=Scheme, E=Subject, F=SubjectName, G=Grade
            if has_names:
                col_reg   = 'A'
                col_name  = 'B'
                col_subj  = 'F'
                col_grade = 'H'
            else:
                col_reg   = 'A'
                col_name  = 'A'   # no name col → show Reg No in both col1 and col2 slots
                col_subj  = 'E'
                col_grade = 'G'

            # Headers for Sections
            subject_perf_sheet.merge_range('A5:C5', 'TOPPERS (S, A+, A)', fmt_section_orange)
            subject_perf_sheet.merge_range('E5:G5', 'NEEDS ATTENTION (F, FE, ABSENT, WITHHELD)', fmt_section_orange)

            headers_sub = ['Register No', 'Student Name' if has_names else 'Reg No (2)', 'Grade']
            for i, h in enumerate(headers_sub):
                subject_perf_sheet.write(5, i, h, fmt_table_header_blue)
                subject_perf_sheet.write(5, i + 4, h, fmt_table_header_blue)

            # Dynamic FILTER formulas — column refs are resolved at report-generation time
            topper_formula = (
                f"=FILTER(CHOOSE({{1,2,3}}, 'All Results'!${col_reg}$2:${col_reg}$10000, "
                f"'All Results'!${col_name}$2:${col_name}$10000, "
                f"'All Results'!${col_grade}$2:${col_grade}$10000), "
                f"('All Results'!${col_subj}$2:${col_subj}$10000=$D$3)*("
                f"('All Results'!${col_grade}$2:${col_grade}$10000=\"S\")"
                f"+('All Results'!${col_grade}$2:${col_grade}$10000=\"A+\")"
                f"+('All Results'!${col_grade}$2:${col_grade}$10000=\"A\")"
                f'), "No Toppers Found")'
            )
            attention_formula = (
                f"=FILTER(CHOOSE({{1,2,3}}, 'All Results'!${col_reg}$2:${col_reg}$10000, "
                f"'All Results'!${col_name}$2:${col_name}$10000, "
                f"'All Results'!${col_grade}$2:${col_grade}$10000), "
                f"('All Results'!${col_subj}$2:${col_subj}$10000=$D$3)*("
                f"('All Results'!${col_grade}$2:${col_grade}$10000=\"F\")"
                f"+('All Results'!${col_grade}$2:${col_grade}$10000=\"FE\")"
                f"+('All Results'!${col_grade}$2:${col_grade}$10000=\"ABSENT\")"
                f"+('All Results'!${col_grade}$2:${col_grade}$10000=\"AB\")"
                f"+('All Results'!${col_grade}$2:${col_grade}$10000=\"WITHHELD\")"
                f'), "No Records Found")'
            )

            # Write to single anchor cell — Excel spill engine will expand rows automatically
            subject_perf_sheet.write_dynamic_array_formula(6, 0, 6, 2, topper_formula, fmt_border)
            subject_perf_sheet.write_dynamic_array_formula(6, 4, 6, 6, attention_formula, fmt_border)

            # Apply conditional formatting for borders (to keep the "section box" look as data spills)
            subject_perf_sheet.conditional_format('A7:C500', {
                'type':     'formula',
                'criteria': '=$A7<>""',
                'format':   fmt_border
            })
            subject_perf_sheet.conditional_format('E7:G500', {
                'type':     'formula',
                'criteria': '=$E7<>""',
                'format':   fmt_border
            })

@app.route('/history')
@login_required
def history_page():
    history = load_history()
    return render_template('history.html', history=history, user=current_user, active_page='history')

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No selected file'}), 400
    
    if file and file.filename.endswith('.pdf'):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{current_user.id}_{file.filename}")
        file.save(filepath)
        
        df, stats, exam_title, college_name = process_pdf(filepath)
        
        if df is None:
            return jsonify({'status': 'error', 'message': 'No data found in PDF. Ensure it is a valid KTU Result PDF.'}), 400
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Sanitize exam title for filename usage
        safe_title = re.sub(r'[^\w\-_]', '_', exam_title)
        safe_title = re.sub(r'_+', '_', safe_title).strip('_')
        
        excel_filename = f"{safe_title}_{current_user.id}_{timestamp}.xlsx"
        excel_path = os.path.join(app.config['UPLOAD_FOLDER'], excel_filename)
        
        latest_year = df['Year'].max()

        generate_excel_report(df, stats, exam_title, excel_path, college_name=college_name, include_perf=False)



        # Save stats JSON
        stats_filename = excel_filename.replace('.xlsx', '.json')
        stats_path = os.path.join(app.config['UPLOAD_FOLDER'], stats_filename)
        with open(stats_path, 'w') as f:
            json.dump(stats, f)
            
        entry = add_to_history(file.filename, excel_filename)
        
        # Latest copy
        shutil.copy2(excel_path, os.path.join(app.config['UPLOAD_FOLDER'], f'latest_{current_user.id}.xlsx'))
        shutil.copy2(stats_path, os.path.join(app.config['UPLOAD_FOLDER'], f'latest_{current_user.id}.json'))
        
        if os.path.exists(filepath):
            os.remove(filepath)
            
        return jsonify({
            'status': 'success',
            'redirect_url': url_for('view_analysis', entry_id=entry['id'])
        })
    
    return jsonify({'status': 'error', 'message': 'Invalid file format'}), 400

# --- Helper Functions for Data Cleaning ---
def clean_reg(text):
    """Normalize registration numbers for robust matching (alphanumeric only, uppercase)."""
    if pd.isna(text): return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).upper()

def clean_name(text):
    """Clean student names by removing non-ASCII garbage and extra whitespace."""
    if pd.isna(text): return ""
    t = "".join(c for c in str(text) if ord(c) < 128)
    return " ".join(t.split()).upper()

@app.route('/map_names/<entry_id>', methods=['GET', 'POST'])
@login_required
def map_names(entry_id):
    history = load_history()
    entry = next((item for item in history if str(item['id']) == entry_id), None)
    
    results_preview = None
    excel_download_filename = entry.get('mapped_excel_filename')
        
    if request.method == 'POST':
        if 'student_list' not in request.files:
            flash('No file uploaded')
            return redirect(request.url)
            
        file = request.files['student_list']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
            
        if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls') or file.filename.endswith('.pdf')):
            try:
                if file.filename.endswith('.pdf'):
                    # PDF Processing
                    temp_pdf = os.path.join(app.config['UPLOAD_FOLDER'], f"mapping_{current_user.id}_{file.filename}")
                    file.save(temp_pdf)
                    
                    extracted_data = extract_students_from_pdf(temp_pdf)
                    if os.path.exists(temp_pdf):
                        os.remove(temp_pdf) # Clean up
                    
                    if not extracted_data:
                        flash('No valid student data (Register No) found in the PDF.')
                        return redirect(request.url)
                    
                    student_names_df = pd.DataFrame(extracted_data)
                else:
                    # Existing Excel Processing
                    # 1. Load Student Names with flexible header detection
                    raw_df = pd.read_excel(file, header=None)
                    
                    # Find the header row by looking for keywords
                    header_row_idx = 0
                    reg_col_idx = None
                    name_col_idx = None
                    
                    # Prioritized keyword categories
                    keywords_reg_primary = ['CANDIDATE CODE', 'REGISTER NO', 'REGISTRATION', 'STUDENT CODE']
                    keywords_reg_secondary = ['CODE', 'REGISTER', 'REG', 'ROLL']
                    
                    keywords_name_primary = ['NAME OF THE STUDENT', 'STUDENT NAME', 'CANDIDATE NAME']
                    keywords_name_secondary = ['NAME', 'STUDENT']
                    
                    for i, row in raw_df.head(15).iterrows():
                        row_vals_raw = [str(val) for val in row if pd.notna(val)]
                        row_vals = [v.upper().strip() for v in row_vals_raw]
                        
                        # Look for primary match first
                        found_reg_p = any(any(k in v for k in keywords_reg_primary) for v in row_vals)
                        found_name_p = any(any(k in v for k in keywords_name_primary) for v in row_vals)
                        
                        # Fallback to secondary if primary not found
                        found_reg_s = any(any(k in v for k in keywords_reg_secondary) for v in row_vals)
                        found_name_s = any(any(k in v for k in keywords_name_secondary) for v in row_vals)
                        
                        if (found_reg_p or found_reg_s) and (found_name_p or found_name_s):
                            header_row_idx = i
                            
                            # Helper to find best column index
                            def find_best_col(r_vals, primary, secondary):
                                # Try primary matches first
                                for idx, v in enumerate(r_vals):
                                    if any(k in v for k in primary): return idx
                                # Then secondary
                                for idx, v in enumerate(r_vals):
                                    if any(k in v for k in secondary): return idx
                                return None

                            reg_col_idx = find_best_col(row_vals, keywords_reg_primary, keywords_reg_secondary)
                            name_col_idx = find_best_col(row_vals, keywords_name_primary, keywords_name_secondary)
                            break
                    
                    if reg_col_idx is None or name_col_idx is None:
                        # Fallback
                        reg_col_idx = 0 if reg_col_idx is None else reg_col_idx
                        name_col_idx = 1 if name_col_idx is None else name_col_idx
                    
                    # Extract data starting from below header
                    student_names_df = raw_df.iloc[header_row_idx+1:].copy()
                    student_names_df = student_names_df[[reg_col_idx, name_col_idx]]
                    student_names_df.columns = ['Register No', 'Student Name']
                               # Data Scrubbing
                student_names_df['Register No'] = student_names_df['Register No'].astype(str)
                student_names_df['Student Name'] = student_names_df['Student Name'].apply(clean_name)
                
                # Create a join key for robust matching
                student_names_df['join_key'] = student_names_df['Register No'].apply(clean_reg)
                
                # Drop empty join keys
                student_names_df = student_names_df[student_names_df['join_key'] != ""]
                
                if student_names_df.empty:
                    flash('No valid data found in the uploaded Excel.')
                    return redirect(request.url)
                
                if not entry:
                    flash('Result entry not found.')
                    return redirect(url_for('dashboard'))
                
                # Determine source data: Always load from the ORIGINAL full Excel
                source_filename = entry.get('source_excel')
                if not source_filename:
                    # Fallback for old entries mapped before this fix
                    if '_WithNames' in entry['excel_filename']:
                        source_filename = entry['excel_filename'].replace('_WithNames', '')
                    else:
                        source_filename = entry['excel_filename']
                
                excel_path = os.path.join(app.config['UPLOAD_FOLDER'], source_filename)
                
                if not os.path.exists(excel_path):
                    flash(f'Original source Excel not found ({source_filename}). Please re-upload the PDF.')
                    return redirect(url_for('dashboard'))
                
                df = pd.read_excel(excel_path, sheet_name='All Results')
                
                # Robust Normalization for original data
                df['join_key'] = df['Register No'].astype(str).apply(clean_reg)
                
                # If 'Student Name' already exists in the original file (e.g. from a previous mapping), 
                # drop it so the new mapping's names take precedence without column suffixing.
                if 'Student Name' in df.columns:
                    df = df.drop(columns=['Student Name'])
                
                # Merge using the join_key
                # We use the name from student_names_df
                matched_names = student_names_df[['join_key', 'Student Name']].drop_duplicates('join_key')
                merged_df = pd.merge(df, matched_names, on='join_key', how='inner')
                
                if merged_df.empty:
                    flash('No matching Registration Numbers found between the PDF and the uploaded Excel.')
                    return redirect(url_for('map_names', entry_id=entry_id))
                
                # Recalculate stats on the filtered set

                # Sort by Register No
                merged_df = merged_df.sort_values(by='Register No')
                
                # 4. Re-calculate Stats for the EXCLUSIVE set
                from utils.pdf_processor import generate_stats
                new_stats = generate_stats(merged_df)
                
                # 5. Re-generate Excel and JSON
                # Update filename to use both the original PDF name and the mapping file name
                orig_base = os.path.splitext(entry['filename'])[0]
                map_base = os.path.splitext(file.filename)[0]
                
                orig_safe = re.sub(r'[^\w\-_]', '_', orig_base)
                map_safe = re.sub(r'[^\w\-_]', '_', map_base)
                
                orig_safe = re.sub(r'_+', '_', orig_safe).strip('_')
                map_safe = re.sub(r'_+', '_', map_safe).strip('_')
                
                timestamp = datetime.now().strftime("%H%M%S")
                new_excel_filename = f"{orig_safe}_{map_safe}_{timestamp}.xlsx"
                
                new_excel_path = os.path.join(app.config['UPLOAD_FOLDER'], new_excel_filename)
                
                # Extract original exam_title and college_name from the source excel
                try:
                    summary_df = pd.read_excel(excel_path, sheet_name='OVERALL SUMMARY', header=None, nrows=5)
                    college_name = str(summary_df.iloc[1, 0]) if len(summary_df) > 1 else "KTU Result Analysis"
                    exam_title = str(summary_df.iloc[2, 0]) if len(summary_df) > 2 else entry['filename'].replace('.pdf', '')
                    
                    if college_name.lower() == 'nan': college_name = "KTU Result Analysis"
                    if exam_title.lower() == 'nan': exam_title = entry['filename'].replace('.pdf', '')
                except Exception:
                    college_name = "KTU Result Analysis"
                    exam_title = entry['filename'].replace('.pdf', '')
                
                generate_excel_report(merged_df, new_stats, exam_title, new_excel_path, college_name=college_name, include_perf=True)
                
                # Save new stats JSON
                new_stats_path = new_excel_path.replace('.xlsx', '.json')
                with open(new_stats_path, 'w') as f:
                    json.dump(new_stats, f)
                
                # Update history (pointing to the new exclusive file)
                for h in history:
                    if str(h['id']) == entry_id:
                        h['mapped_excel_filename'] = new_excel_filename
                        break
                save_history(history)
                
                # Prepare Preview Data for Display
                preview_students = merged_df.groupby('Register No').first().reset_index()
                results_preview = preview_students[['Register No', 'Student Name', 'SGPA']].sort_values(by='Register No').to_dict('records')
                excel_download_filename = new_excel_filename
                
                flash('Exclusive results generated successfully!')
                
            except Exception as e:
                flash(f'Error processing file: {str(e)}')
                return redirect(request.url)
        else:        
            flash('Invalid file format. Please upload an Excel or PDF file.')
            return redirect(request.url)
            
    return render_template('map_names.html', 
                          entry_id=entry_id, 
                          filename=entry['filename'], 
                          user=current_user, 
                          active_page='converter',
                          results=results_preview,
                          download_file=excel_download_filename)

@app.route('/view/<entry_id>')
@login_required
def view_analysis(entry_id):
    history = load_history()
    entry = next((item for item in history if str(item['id']) == entry_id), None)
    
    if not entry:
        return "Analysis not found", 404
        
    excel_path = os.path.join(app.config['UPLOAD_FOLDER'], entry['excel_filename'])
    if not os.path.exists(excel_path):
        return "Excel file not found", 404
        
    try:
        # Try loading cached stats JSON first (very fast)
        stats_path = excel_path.replace('.xlsx', '.json')
        if os.path.exists(stats_path):
            with open(stats_path, 'r') as f:
                stats = json.load(f)
        else:
            # Fallback: Load from Excel (slow)
            df = pd.read_excel(excel_path, sheet_name='All Results')
            stats = generate_stats(df)
        
        return render_template('results.html', stats=stats, user=current_user, filename=entry['filename'], excel_filename=entry['excel_filename'], entry_id=entry_id)
    except Exception:
        return "Error loading analysis", 500

@app.route('/student_details/<entry_id>')
@login_required
def student_details(entry_id):
    history = load_history()
    entry = next((item for item in history if str(item['id']) == entry_id), None)
    
    if not entry:
        return "Analysis not found", 404
        
    excel_path = os.path.join(app.config['UPLOAD_FOLDER'], entry['excel_filename'])
    if not os.path.exists(excel_path):
        return "Excel file not found", 404
        
    try:
        stats_path = excel_path.replace('.xlsx', '.json')
        if os.path.exists(stats_path):
            with open(stats_path, 'r') as f:
                stats = json.load(f)
        else:
            df = pd.read_excel(excel_path, sheet_name='All Results')
            stats = generate_stats(df)
        
        return render_template('student_details.html', stats=stats, user=current_user, entry_id=entry_id)
    except Exception:
        return "Error loading analysis", 500

@app.route('/download')
@app.route('/download/<filename>')
@login_required
def download_file(filename=None):
    if filename:
        # Security check: Does this file belong to the user?
        history = load_history()
        if not any(h['excel_filename'] == filename or h.get('mapped_excel_filename') == filename for h in history):
            return "Access denied", 403
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    else:
        path = os.path.join(app.config['UPLOAD_FOLDER'], f'latest_{current_user.id}.xlsx')
        
    if os.path.exists(path):
        download_name = filename if filename else 'result_analysis.xlsx'
        return send_file(path, as_attachment=True, download_name=download_name)
    return "File not found", 404

@app.route('/delete/<entry_id>')
@login_required
def delete_entry(entry_id):
    delete_from_history(entry_id)
    return redirect(url_for('dashboard'))

@app.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    entry_ids = request.form.getlist('entry_ids')
    if entry_ids:
        for entry_id in entry_ids:
            delete_from_history(entry_id)
    return redirect(url_for('dashboard'))

@app.route('/clear_history')
@login_required
def clear_all_history():
    history = load_history()
    for entry in history:
        excel_path = os.path.join(app.config['UPLOAD_FOLDER'], entry['excel_filename'])
        if os.path.exists(excel_path):
            os.remove(excel_path)
        
        # Also remove cached stats JSON
        stats_path = excel_path.replace('.xlsx', '.json')
        if os.path.exists(stats_path):
            os.remove(stats_path)
    
    # Save an empty list for this user (load_history already filters by user)
    save_history([])
    return redirect(url_for('dashboard'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # Get and normalize email
        raw_email = request.form.get('email', '')
        email = raw_email.strip().lower()
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            token = s.dumps(email, salt='password-reset-salt')
            
            # 1. First, check if a domain is configured in .env (for college official site)
            app_domain = os.getenv('APP_DOMAIN')
            
            if app_domain:
                reset_url = f"{app_domain.rstrip('/')}/reset_password/{token}"
            else:
                # 2. Otherwise, use the local network IP (Robust method for WiFi demo)
                import socket
                try:
                    s_ip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s_ip.connect(("8.8.8.8", 80))  # Doesn't actually send data, just finds the local interface
                    local_ip = s_ip.getsockname()[0]
                    s_ip.close()
                except Exception:
                    local_ip = '127.0.0.1'
                reset_url = f"http://{local_ip}:5000/reset_password/{token}"
            
            
            msg = Message('Password Reset Request',
                          recipients=[email])
            
            # Plain Text Fallback
            msg.body = f"To reset your password, visit the following link: {reset_url}"
            
            # Professional HTML Version with Button
            msg.html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px; color: #1e293b;">
                <h2 style="color: #9333EA; text-align: center;">KTU Result Analyzer</h2>
                <hr style="border: 0; border-top: 1px solid #f1f5f9; margin: 20px 0;">
                <p>Hello,</p>
                <p>You requested to reset your password. Click the button below to set a new one:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background-color: #9333EA; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Reset Password</a>
                </div>
                <p style="font-size: 0.875rem; color: #64748b;">If the button above doesn't work, copy and paste this link into your browser:</p>
                <p style="font-size: 0.875rem; color: #3b82f6; word-break: break-all;">{reset_url}</p>
                <hr style="border: 0; border-top: 1px solid #f1f5f9; margin: 20px 0;">
                <p style="font-size: 0.75rem; color: #94a3b8; text-align: center;">If you did not request this, please ignore this email.</p>
            </div>
            """
            
            try:
                mail.send(msg)
                flash('An email has been sent with instructions to reset your password.')
            except Exception:
                flash('An email has been sent with instructions to reset your password. (Dev: Check console for link)')
            
            return redirect(url_for('login'))
        else:
            flash('If an account exists with that email, a reset link will be sent.')
            return redirect(url_for('login'))
            
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)  # 1 hour expiry
    except Exception:
        flash('The reset link is invalid or has expired.')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        email_clean = email.strip().lower()
        user = User.query.filter_by(email=email_clean).first()
        
        if user:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash('Your password has been updated!')
            return redirect(url_for('login'))
        else:
            flash('User not found.')
            return redirect(url_for('login'))
            
    return render_template('reset_password.html', token=token)

# Create database tables and seed data
with app.app_context():
    db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Seed a default admin user for demonstration
    from werkzeug.security import generate_password_hash
    admin_email = "admin@ktu.edu"
    if not User.query.filter_by(email=admin_email).first():
        admin_user = User(
            email=admin_email,
            name="KTU Admin",
            password=generate_password_hash("admin123")
        )
        db.session.add(admin_user)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
