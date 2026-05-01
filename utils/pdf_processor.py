import fitz
import pandas as pd
import re
import os
import json

# Pre-compile regex for performance
# MBA student IDs (e.g., BMC24MBA01) have 2 digits at end; BTech has 3.
REG_NO_PATTERN = re.compile(r'\b(([A-Z]{3,4})(\d{2})([A-Z]{2,4})(\d{2,3}))\b')
# Only match valid KTU grades to avoid picking up credits or other numbers in parentheses
# Added \s* to handle potential spacing in PDF text (e.g., "CST401( F )")
# All valid KTU grades: 2019 uses P/D(6.0), 2024 uses D(4.0)/PASS. Ab = Absent/Deferred.
# MBA 2020 uses O (10.0) instead of S. Added 'Ab' for consistency.
VALID_GRADES = ['O', 'S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'F', 'FE', 'Absent', 'Ab', 'Withheld', 'PASS', 'Pass', 'I']
# MBA Course codes (e.g., 20MBA101) start with digits.
# Liberal regex to capture ANY text inside brackets as requested: "everything... (pass) ("anything which inside the bracket ")")
COURSE_PATTERN = re.compile(r'\b([A-Z0-9]{5,10})\s*\(\s*([^)]+)\s*\)', re.IGNORECASE)
# Pattern to match subject code and its full name (handles vertical and horizontal layouts)
SUBJECT_NAME_PATTERN = re.compile(r'\b([A-Z0-9]{5,10})\s+([A-Z][A-Z0-9\s\-&/\(\)]{5,100}?)(?=\s+[A-Z0-9]{5,10}\b|\s*\nRegister No|\s*\nCourse Code|\s{5,}|$)', re.MULTILINE)

# KTU 2019 Scheme Grade Points — S=10, A+=9, A=8.5, B+=8, B=7.5, C+=7, C=6.5, D=6, P=5.5, F/FE/Ab=0
GRADE_POINTS_2019 = {
    'S': 10, 'O': 10, 'A+': 9, 'A': 8.5, 'B+': 8, 'B': 7.5, 'C+': 7, 'C': 6.5, 'D': 6, 'P': 5.5,
    'F': 0, 'FE': 0, 'Absent': 0, 'Ab': 0, 'Withheld': 0, 'PASS': 0
}
 
# KTU 2024 Scheme Grade Points — D=4.0 (Low Pass), no P grade, PASS used for HMC/PW courses
# S=10, A+=9, A=8.5, B+=8, B=7.5, C+=7, C=6.5, D=4, F/FE/Ab=0
GRADE_POINTS_2024 = {
    'S': 10, 'O': 10, 'A+': 9, 'A': 8.5, 'B+': 8, 'B': 7.5, 'C+': 7, 'C': 6.5, 'D': 6, 'P': 5.5,
    'F': 0, 'FE': 0, 'Absent': 0, 'Ab': 0, 'Withheld': 0, 'PASS': 0
}

# KTU MBA 2020 Scheme Grade Points — O=10, A+=9, A=8.5, B+=8, B=7.5, C+=7, C=6.5, D=6, P=5.5
GRADE_POINTS_MBA_2020 = {
    'O': 10, 'A+': 9, 'A': 8.5, 'B+': 8, 'B': 7.5, 'C+': 7, 'C': 6.5, 'D': 6, 'P': 5.5,
    'F': 0, 'FE': 0, 'Absent': 0, 'Ab': 0, 'Withheld': 0, 'PASS': 0, 'I': 0
}

# Default (backward compat)
GRADE_POINTS = GRADE_POINTS_2019

def get_grade_points(scheme):
    if scheme == "2024":
        return GRADE_POINTS_2024
    elif scheme == "2019":
        return GRADE_POINTS_2019
    elif scheme == "MBA_2020":
        return GRADE_POINTS_MBA_2020
    else:
        return GRADE_POINTS_2024  # default safer

def get_credits_map():
    try:
        # Move up from utils to find credits.json in project root
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        credits_path = os.path.join(root_dir, 'credits.json')
        if os.path.exists(credits_path):
            with open(credits_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading credits.json: {e}")
    return {}

def calculate_sgpa(subjects, credits_lookup, scheme='2019'):
    """
    subjects: { 'SUB_CODE': 'GRADE' }
    credits_lookup: flat dict { 'SUB_CODE': credits }
    scheme: '2024', '2019', or 'MBA_2020'
    """
    grade_pts = get_grade_points(scheme)

    total_weighted_points = 0
    total_credits = 0
    
    for sub, grade in subjects.items():
        sub = sub.strip().upper()

        # PASS-graded courses (HMC/PW: Health & Wellness, Life Skills etc.) are
        # co-curricular courses that are EXCLUDED from SGPA in both schemes.
        # F, FE, Ab ARE included (with 0 grade points) as per KTU rules.
        if grade == 'PASS':
            continue

        # 2024 Scheme uses templates like PCXXT302 or GYMAT301 in credits.json
        # whereas PDF has specific codes like PCCST302 or GAMAT301.
        credit = credits_lookup.get(sub)
        
        if credit is None and scheme == '2024':
            # Try template matching
            for template, value in credits_lookup.items():
                # Replace templates like PCXXT, GYMAT, GXEST with regex patterns
                # using a single pass to avoid replacing within already replaced strings
                pattern = re.sub(r'XXXX|XX|[YXZN]', lambda m: 
                                '[A-Z]{2,4}' if m.group(0) == 'XXXX' else 
                                '[A-Z]{2,3}' if m.group(0) == 'XX' else 
                                '[0-9N]' if m.group(0) == 'N' else '[A-Z]', 
                                template)
                
                if re.fullmatch(pattern, sub):
                    credit = value
                    break

        if credit is None:
            credit = 4  # Default to 4 credits if still not found
            
        points = grade_pts.get(grade, 0)

        total_weighted_points += (points * credit)
        total_credits += credit

    if total_credits == 0:
        return None
    return round(total_weighted_points / total_credits, 2)


def process_pdf(pdf_path):
    student_records = {} # reg_no -> {'Year', 'Dept', 'Subjects': {sub: grade}}
    exam_title = "KTU Result Analysis"
    
    try:
        doc = fitz.open(pdf_path)
        
        # 1. Get Exam Title from first few pages (Header info)
        header_text = ""
        # Scan first 10 pages to be safe, especially for large colleges
        for i in range(min(10, len(doc))):
            header_text += doc[i].get_text() + "\n"
        
        title_match = re.search(r'([A-Z].*Exam.*2\d{3}.*)', header_text)
        if title_match:
            exam_title = title_match.group(1).strip()
            
        # 1.1 Get College Name (Exam Centre)
        college_name = "KTU Result Analysis"
        # Look for "Centre" or "College" prefix followed by the name, ignoring case
        # Adjusted to handle multiple spaces, dashes, or colons
        college_match = re.search(r'(?:CENTRE|COLLEGE|INSTITUTION)\s*[:\-]?\s*([A-Z][A-Z\s]{5,100})', header_text, re.IGNORECASE)
        if college_match:
            college_name = college_match.group(1).strip()
            # Clean up trailing junk if any
            college_name = re.split(r'[\(\n\r]', college_name)[0].strip()
        elif title_match:
            # Fallback: Sometimes the college is mentioned in the line below the title
            title_end = title_match.end()
            after_title = header_text[title_end:title_end+200]
            # Try to find a long capitalized line which might be the college
            lines = [l.strip() for l in after_title.split('\n') if len(l.strip()) > 15]
            if lines:
                college_name = lines[0]

        # 2. Extract full text and clean header junk from each page
        full_text_list = []
        junk_patterns = [
            r'APJ ABDUL KALAM TECHNOLOGICAL UNIVERSITY',
            r'Academic Audit Cell',
            r'Subject Details',
            r'Page \d+ of \d+',
            r'Controller of Examinations',
            r'^Result\s+Analysis$',
            r'^B\.Tech'
        ]
        
        for page in doc:
            page_text = page.get_text()
            clean_lines = []
            for line in page_text.split('\n'):
                line = line.strip()
                if not line: continue
                # Skip if line matches any junk pattern
                if any(re.search(p, line, re.IGNORECASE) for p in junk_patterns):
                    continue
                # Skip lines that are just dashes or separator-like
                if re.match(r'^[-=\s]+$', line):
                    continue
                clean_lines.append(line)
            
            full_text_list.append("\n".join(clean_lines))
            full_text_list.append("\n---PAGE_SEP---\n")
            
        full_text = "".join(full_text_list)
        
        # 2.5 Extract Subject Names (Mapping Code -> Name)
        subject_names = {}
        # Search in the first few pages where subject details are usually listed
        subject_matches = SUBJECT_NAME_PATTERN.findall(full_text[:20000]) # Focus on start
        for sub_code, sub_name in subject_matches:
            sub_code = sub_code.strip().upper()
            if sub_code not in subject_names:
                # Clean up whitespace and newlines from name
                subject_names[sub_code] = " ".join(sub_name.split()).strip()
        
        # 3. Find all potential student ID starts
        matches = list(REG_NO_PATTERN.finditer(full_text))
        
        for i in range(len(matches)):
            match = matches[i]
            reg_no = match.group(1)
            year = f"20{match.group(3)}"
            dept = match.group(4)
            
            if reg_no not in student_records:
                student_records[reg_no] = {
                    'Year': year,
                    'Dept': dept,
                    'Subjects': {}
                }
            
            # Text chunk until next ID
            start_pos = match.start()
            end_pos = matches[i+1].start() if i+1 < len(matches) else len(full_text)
            chunk = full_text[start_pos:end_pos]
            
            # Find Courses
            courses = COURSE_PATTERN.findall(chunk)
            for sub, grade in courses:
                # Normalize grade to uppercase and unify AB/ABSENT
                g_norm = grade.strip().upper()
                if g_norm == 'AB': g_norm = 'ABSENT'
                student_records[reg_no]['Subjects'][sub] = g_norm

            if not courses:
                if 'withheld' in chunk.lower():
                    student_records[reg_no]['Status'] = 'WITHHELD'
                elif 'absent' in chunk.lower() or 'cancelled' in chunk.lower():
                    student_records[reg_no]['Status'] = 'ABSENT'

        doc.close()
        
        # 4. Flatten dict into data list and calculate SGPA
        credits_data = get_credits_map()
        
        # Try to find semester from exam title (e.g., "S8")
        sem_match = re.search(r'\b(S[1-8])\b', exam_title)
        semester = sem_match.group(1) if sem_match else None
        
        # Mapping from Register Number Dept Codes to JSON keys
        DEPT_MAP = {
            'CS': 'CSE',
            'AD': 'AI',
            'EE': 'EEE',
            'EC': 'ECE',
            'ME': 'ME',
            'CE': 'CE'
        }
        
        # Mapping from Dept Code to 2024 Scheme Group
        GROUP_MAP = {
            # Group A: Computer and Information Science
            'CS': 'Group_A', 'AD': 'Group_A', 'IT': 'Group_A',
            # Group B: Electrical Science
            'EE': 'Group_B', 'EC': 'Group_B', 'BM': 'Group_B', 'IC': 'Group_B', 'AE': 'Group_B',
            # Group C: Physical Science
            'CE': 'Group_C', 'CH': 'Group_C', 'ME': 'Group_C', 'AU': 'Group_C', 'PE': 'Group_C',
            # Group D: Life Science
            'BT': 'Group_D', 'FT': 'Group_D'
        }
        
        data = []
        for reg_no, info in student_records.items():
            if not info.get('Subjects'):
                if 'Status' in info and info['Status'] in ['WITHHELD', 'ABSENT']:
                    scheme_type = 'MBA_2020' if info['Dept'] == 'MBA' else ('2024' if info['Year'] == '2024' else '2019')
                    data.append({
                        'Register No': reg_no,
                        'Year': info['Year'],
                        'Dept': info['Dept'],
                        'Scheme': scheme_type,
                        'Subject': 'NO_SUBJECTS',
                        'Subject Name': f"Entire Result {info['Status']}",
                        'Grade': info['Status'],
                        'SGPA': 0.0
                    })
                continue
            
            # Determine credits lookup for this specific student
            # Credits JSON structure: 
            # 2019: "KTU_2019_Scheme_DEPT" -> "SX" -> {sub: credit}
            # 2024: "KTU_2024_Scheme_Group_X" -> "SX" -> {sub: credit}
            # MBA:  "KTU_MBA_2020_Scheme" -> "SX" -> {sub: credit}
            
            scheme_type = '2019'
            if info['Dept'] == 'MBA':
                dept_key = "KTU_MBA_2020_Scheme"
                # MBA 2024 uses same grade points as 2019 scheme
                scheme_type = '2019' if info['Year'] == '2024' else 'MBA_2020'
            elif info['Year'] == '2024':
                group = GROUP_MAP.get(info['Dept'], 'Group_A') # Default to Group A
                dept_key = f"KTU_2024_Scheme_{group}"
                scheme_type = '2024'
            else:
                long_dept = DEPT_MAP.get(info['Dept'], info['Dept'])
                dept_key = f"KTU_2019_Scheme_{long_dept}"
                scheme_type = '2019'
            
            # Extract credits for the specific department/group and semester
            credits_lookup = {}
            if credits_data and dept_key in credits_data:
                if semester and semester in credits_data[dept_key]:
                    credits_lookup = credits_data[dept_key][semester]
            
            # Identify if student has any fail grades
            fail_grades = ['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I']
            has_failed = any(g in fail_grades for g in info['Subjects'].values())
            
            if has_failed:
                sgpa = 0.0
            else:
                sgpa = calculate_sgpa(info['Subjects'], credits_lookup, scheme=scheme_type)

            
            for sub, grade in info['Subjects'].items():
                sub_upper = sub.strip().upper()
                data.append({
                    'Register No': reg_no,
                    'Year': info['Year'],
                    'Dept': info['Dept'],
                    'Scheme': scheme_type,
                    'Subject': sub_upper,
                    'Subject Name': subject_names.get(sub_upper, sub_upper),
                    'Grade': grade,
                    'SGPA': sgpa
                })


        df = pd.DataFrame(data)
        if df.empty: return None, None, exam_title, college_name
        
        # Post-process entirely withheld students to assign them the typical peer subjects
        # This naturally triggers multi-subject arrears (e.g. 8 arrears) and populates the subject dashboard for them
        no_subj_students = df[df['Subject'] == 'NO_SUBJECTS']
        new_rows = []
        if not no_subj_students.empty:
            for _, stu in no_subj_students.iterrows():
                dept = stu['Dept']
                year = stu['Year']
                peer_df = df[(df['Dept'] == dept) & (df['Year'] == year) & (df['Subject'] != 'NO_SUBJECTS')]
                
                if peer_df.empty:
                    new_rows.append(stu.to_dict())
                    continue
                    
                peer_sub_counts = peer_df['Subject'].value_counts()
                typical_subs = peer_sub_counts[peer_sub_counts > peer_df['Register No'].nunique() * 0.3].index.tolist()
                if not typical_subs:
                    typical_subs = peer_sub_counts.index.tolist()[:8]
                    
                for sub in typical_subs:
                    new_row = stu.to_dict().copy()
                    new_row['Subject'] = sub
                    sub_names = peer_df[peer_df['Subject'] == sub]['Subject Name'].unique()
                    new_row['Subject Name'] = sub_names[0] if len(sub_names) > 0 else sub
                    new_rows.append(new_row)
                    
            df = df[df['Subject'] != 'NO_SUBJECTS']
            if new_rows:
                df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        
        stats = generate_stats(df)
        return df, stats, exam_title, college_name

    except Exception as e:
        print(f"Error processing PDF: {e}")
        return None, None, exam_title, college_name

def generate_stats(df):
    if df.empty: return {}
    # Clean keys to ensure dashboard matching works
    df['Subject'] = df['Subject'].astype(str).str.strip().str.upper()
    df['Dept'] = df['Dept'].astype(str).str.strip().str.upper()
    latest_year = df['Year'].max()
    total_students = int(df['Register No'].nunique())
    regular_mask = df['Year'] == latest_year
    regular_students_count = int(df[regular_mask]['Register No'].nunique())
    
    df['is_fail'] = df['Grade'].isin(['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I'])
    total_fail = int(df['is_fail'].sum())
    total_pass = len(df) - total_fail

    # Grade list for distribution (O, S, ...)
    grade_order = ['O', 'S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I']
    
    def get_grade_dist(sub_df):
        dist = sub_df['Grade'].value_counts().to_dict()
        return {g: int(dist.get(g, 0)) for g in grade_order}

    def get_student_lists(sub_df):
        sub_df = sub_df.copy()
        sub_df['Grade'] = sub_df['Grade'].astype(str).str.strip()
        has_name = 'Student Name' in sub_df.columns
        
        # 1. Top Scorers (Grades: O, S, A+, A)
        top_mask = sub_df['Grade'].isin(['O', 'S', 'A+', 'A'])
        top_students = sub_df[top_mask].sort_values(by=['Grade', 'Register No'])
        
        if has_name:
            topper_8_above = [[str(r).strip(), str(g).strip(), str(n).strip()] for r, g, n in zip(top_students[top_students['Grade'].isin(['O', 'S', 'A+'])]['Register No'], top_students[top_students['Grade'].isin(['O', 'S', 'A+'])]['Grade'], top_students[top_students['Grade'].isin(['O', 'S', 'A+'])]['Student Name'])]
            above_7_5 = [[str(r).strip(), str(g).strip(), str(n).strip()] for r, g, n in zip(top_students[top_students['Grade'] == 'A']['Register No'], top_students[top_students['Grade'] == 'A']['Grade'], top_students[top_students['Grade'] == 'A']['Student Name'])]
        else:
            topper_8_above = [[str(r).strip(), str(g).strip()] for r, g in zip(top_students[top_students['Grade'].isin(['O', 'S', 'A+'])]['Register No'], top_students[top_students['Grade'].isin(['O', 'S', 'A+'])]['Grade'])]
            above_7_5 = [[str(r).strip(), str(g).strip()] for r, g in zip(top_students[top_students['Grade'] == 'A']['Register No'], top_students[top_students['Grade'] == 'A']['Grade'])]
        
        # 2. Other Passed (B+, B, C+, C, D, P)
        other_grades_mask = sub_df['Grade'].isin(['B+', 'B', 'C+', 'C', 'D', 'P'])
        other_passed_df = sub_df[other_grades_mask].sort_values(by='Register No')
        
        if has_name:
            other_passed = [[str(r).strip(), str(g).strip(), str(n).strip()] for r, g, n in zip(other_passed_df['Register No'], other_passed_df['Grade'], other_passed_df['Student Name'])]
        else:
            other_passed = [[str(r).strip(), str(g).strip()] for r, g in zip(other_passed_df['Register No'], other_passed_df['Grade'])]
        
        # 3. Failed detailed
        fail_mask = sub_df['Grade'].isin(['F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I'])
        failed_df = sub_df[fail_mask].sort_values(by='Register No')
        
        if has_name:
            fail_data = [[str(r).strip(), str(n).strip()] for r, n in zip(failed_df['Register No'], failed_df['Student Name'])]
        else:
            fail_data = [[str(r).strip()] for r in failed_df['Register No']]
        
        return {
            'topper_8_above': topper_8_above,
            'above_7_5': above_7_5,
            'other_passed': other_passed,
            'fail_detailed': fail_data
        }

    stats = {
        'total_students': total_students,
        'regular_count': regular_students_count,
        'total_entries': len(df),
        'total_pass': total_pass,
        'total_fail': total_fail,
        'subjects': sorted(df['Subject'].unique().tolist()),
        'subject_names': df.groupby('Subject')['Subject Name'].first().to_dict(),
        'departments': sorted(df['Dept'].unique().tolist()),
        'dept_sub_stats': {},
        'dept_summary': {},
        'overall_grade_dist': get_grade_dist(df)
    }
    
    subj_grouped = df.groupby(['Dept', 'Year', 'Subject'])
    
    for (dept, year, sub), sub_df in subj_grouped:
        if sub == 'NO_SUBJECTS':
            continue
            
        total = len(sub_df)
        fail = int(sub_df['is_fail'].sum())
        
        # Robust initialization of nested dictionary with explicit type checks
        if not isinstance(stats.get('dept_sub_stats'), dict):
            stats['dept_sub_stats'] = {}
            
        if dept not in stats['dept_sub_stats'] or not isinstance(stats['dept_sub_stats'][dept], dict):
            stats['dept_sub_stats'][dept] = {}
        
        dept_dict = stats['dept_sub_stats'][dept]
        
        if year not in dept_dict or not isinstance(dept_dict[year], dict):
            dept_dict[year] = {}
            
        year_dict = dept_dict[year]
            
        year_dict[sub] = {
            'pass': total - fail, 
            'fail': fail, 
            'total': total,
            'grade_dist': get_grade_dist(sub_df),
            'student_lists': get_student_lists(sub_df)
        }

    dept_grouped = df.groupby('Dept')
    for dept, dept_df in dept_grouped:
        dept_total = int(dept_df['Register No'].nunique())
        
        main_year = dept_df['Year'].value_counts().idxmax()
        # Include main batch AND lateral entry students (who join the next year)
        current_years = [y for y in dept_df['Year'].unique() if y >= main_year]
        dept_reg_df = dept_df[dept_df['Year'].isin(current_years)]
        
        dept_reg_count = int(dept_reg_df['Register No'].nunique())
        
        # Calculate pass/fail for regular students in this dept
        # A student passes if they have no fail grades in any subject
        reg_pass_count = 0
        if dept_reg_count > 0:
            reg_student_fails = dept_reg_df.groupby('Register No')['is_fail'].any()
            reg_pass_count = int(dept_reg_count - reg_student_fails.sum())

        stats['dept_summary'][dept] = {
            'count': dept_total, 
            'regular': dept_reg_count, 
            'backlog': dept_total - dept_reg_count, 
            'entries': len(dept_df),
            'reg_pass': reg_pass_count,
            'reg_fail': dept_reg_count - reg_pass_count,
            'grade_dist': get_grade_dist(dept_reg_df if not dept_reg_df.empty else dept_df),
            'student_lists': get_student_lists(dept_reg_df if not dept_reg_df.empty else dept_df)
        }
    return stats

def extract_students_from_pdf(pdf_path):
    """
    Extracts (Register No, Student Name) pairs from a PDF.
    Attempts to find names by looking for capitalized text near valid Register Numbers.
    """
    results = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            # Get text as blocks to capture associated text grouping
            blocks = page.get_text("blocks")
            for block in blocks:
                # blocks[4] is the text content
                text = block[4]
                # Clean up non-printable characters
                text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', text)
                
                # Search for Reg No pattern
                match = REG_NO_PATTERN.search(text.upper())
                if match:
                    reg_no = match.group(1)
                    # Heuristic: The name is likely the other significant text in the same block
                    # after removing the Reg No and stripping whitespace/noise.
                    # We also remove common words like 'Register', 'Name', etc.
                    clean_text = text.replace(match.group(0), '').strip()
                    # Filter for lines that look like names
                    potential_names = [line.strip() for line in clean_text.split('\n') if len(line.strip()) > 2]
                    
                    found_name = ""
                    for pn in potential_names:
                        # Clean name (alphabetical characters only)
                        name = re.sub(r'[^a-zA-Z\s\.]', '', pn).strip().upper()
                        # Reject common headers or single words if they don't look like names
                        if len(name) > 3 and not any(k in name for k in ['REGISTER', 'NAME', 'INTERNAL', 'MARK']):
                            found_name = name
                            break
                    
                    results.append({'Register No': reg_no, 'Student Name': found_name})
                    
        doc.close()
    except Exception as e:
        print(f"Error extracting students from PDF: {e}")
        
    # De-duplicate by Register No, prioritizing those with names found
    final_dict = {}
    for item in results:
        reg = item['Register No']
        name = item['Student Name']
        if reg not in final_dict or (not final_dict[reg] and name):
            final_dict[reg] = name
            
    # Final output as list of dicts
    return [{'Register No': k, 'Student Name': v} for k, v in final_dict.items()]
