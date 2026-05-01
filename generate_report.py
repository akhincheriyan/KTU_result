import os
import sys
import pandas as pd
import xlsxwriter
from io import BytesIO

# Add project root to sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from utils.pdf_processor import process_pdf

def generate_excel_from_pdf(pdf_path, output_path):
    # 1. Process PDF
    df, stats, exam_title, college_name = process_pdf(pdf_path)
    if df is None:
        print("Error processing PDF.")
        return

    # 2. Mimic app.py Excel generation logic (Refined with new Topper/Failed lists)
    workbook = xlsxwriter.Workbook(output_path)
    
    # Formats (Consistent with app.py)
    fmt_header_main = workbook.add_format({'bold': True, 'font_size': 18, 'align': 'center', 'valign': 'vcenter', 'font_name': 'Arial', 'bg_color': '#1F4E78', 'font_color': 'white'})
    fmt_section_orange = workbook.add_format({'bold': True, 'bg_color': '#FCE4D6', 'border': 1, 'align': 'center', 'font_color': 'black'})
    fmt_table_header_blue = workbook.add_format({'bold': True, 'bg_color': '#DDEBF7', 'border': 1, 'align': 'center', 'font_color': 'black', 'text_wrap': True, 'font_size': 9})
    fmt_border = workbook.add_format({'border': 1, 'align': 'center', 'font_color': 'black'})
    fmt_no_border = workbook.add_format({'align': 'center', 'font_color': 'black'})
    fmt_percent = workbook.add_format({'num_format': '0.0"%"', 'border': 1, 'align': 'center', 'font_color': 'black'})
    fmt_sgpa_no_border = workbook.add_format({'num_format': '0.00', 'align': 'center', 'font_color': 'black'})
    fmt_cond_border = workbook.add_format({'border': 1, 'font_color': 'black'})
    fmt_cond_sgpa = workbook.add_format({'num_format': '0.00', 'border': 1, 'align': 'center', 'font_color': 'black'})
    fmt_alt_row_1 = workbook.add_format({'bg_color': '#EFF6FF', 'border': 1, 'align': 'center'}) # Light Blue
    fmt_alt_row_2 = workbook.add_format({'bg_color': '#ECFDF5', 'border': 1, 'align': 'center'}) # Light Green
    
    # Sheet 1: OVERALL SUMMARY
    summary_sheet = workbook.add_worksheet('OVERALL SUMMARY')
    summary_sheet.activate() # Focus here
    summary_sheet.merge_range('A1:G1', college_name if college_name else "KTU RESULT ANALYSIS", fmt_header_main)
    
    headers = ['Department Name', 'Total Regular', 'Total Pass', 'Total Fail', 'Pass %', 'Fail %', 'Avg SGPA']
    for i, h in enumerate(headers):
        summary_sheet.write(11, i, h, fmt_table_header_blue)
    
    # Add Subject Names mapping for lookup
    sub_names = stats.get('subject_names', {})
    
    row_idx = 12
    for i, dept in enumerate(stats.get('departments', [])):
        dept_stats = stats['dept_summary'].get(dept, {})
        pass_perc = (dept_stats.get('reg_pass', 0) / dept_stats.get('regular', 1) * 100)
        fmt_row = fmt_alt_row_1 if i % 2 == 0 else fmt_alt_row_2
        fmt_pct = workbook.add_format({'num_format': '0.0"%"', 'border': 1, 'align': 'center', 'font_color': 'black', 'bg_color': fmt_row.bg_color})
        fmt_sg = workbook.add_format({'num_format': '0.00', 'align': 'center', 'font_color': 'black', 'bg_color': fmt_row.bg_color, 'border': 1})
        
        summary_sheet.write(row_idx, 0, dept, fmt_row)
        summary_sheet.write(row_idx, 1, dept_stats.get('regular', 0), fmt_row)
        summary_sheet.write(row_idx, 2, dept_stats.get('reg_pass', 0), fmt_row)
        summary_sheet.write(row_idx, 3, dept_stats.get('regular', 0) - dept_stats.get('reg_pass', 0), fmt_row)
        summary_sheet.write(row_idx, 4, pass_perc, fmt_pct)
        summary_sheet.write(row_idx, 5, 100 - pass_perc, fmt_pct)
        summary_sheet.write(row_idx, 6, dept_stats.get('avg_sgpa', 0), fmt_sg)
        row_idx += 1
        
    # Hidden Data Sheet for Charts
    data_sheet = workbook.add_worksheet('_DATA_')
    data_sheet.hide()
    
    grade_headers = ['O', 'S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'PASS', 'F', 'FE', 'ABSENT', 'AB', 'WITHHELD', 'I']
    data_row_idx = 1
    
    # Fill _DATA_ sheet
    for dept in stats.get('departments', []):
        dept_info = stats['dept_summary'].get(dept, {})
        # Overall Dept
        row_cells = [f"{dept}_Overall Department", dept_info.get('regular', 0), dept_info.get('reg_pass', 0), 
                     dept_info.get('regular', 0) - dept_info.get('reg_pass', 0), 0, 0]
        # Grades
        d_dist = dept_info.get('grade_dist', {})
        for g in grade_headers:
            row_cells.append(d_dist.get(g, 0))
        data_sheet.write_row(data_row_idx, 0, row_cells)
        data_row_idx += 1
        
        # Subjects
        for sub, s_stats in stats.get('dept_sub_stats', {}).get(dept, {}).get(int(list(stats['dept_sub_stats'][dept].keys())[0]), {}).items():
            s_appeared = s_stats.get('total', 0)
            s_passed = s_stats.get('pass', 0)
            s_row = [f"{dept}_{sub}", s_appeared, s_passed, s_appeared - s_passed, 0, 0]
            s_dist = s_stats.get('grade_dist', {})
            for g in grade_headers:
                s_row.append(s_dist.get(g, 0))
            data_sheet.write_row(data_row_idx, 0, s_row)
            data_row_idx += 1

    # Formats for Cards
    fmt_card_title = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#F3F4F6', 'border': 1, 'font_size': 10})
    fmt_card_val_blue = workbook.add_format({'bold': True, 'align': 'center', 'font_color': '#1E40AF', 'font_size': 14, 'border': 1})
    fmt_card_val_green = workbook.add_format({'bold': True, 'align': 'center', 'font_color': '#15803D', 'font_size': 14, 'border': 1})
    fmt_card_val_red = workbook.add_format({'bold': True, 'align': 'center', 'font_color': '#B91C1C', 'font_size': 14, 'border': 1})
    fmt_card_perc = workbook.add_format({'bold': True, 'align': 'center', 'font_size': 14, 'border': 1, 'num_format': '0.0"%"'})
    fmt_dropdown_box = workbook.add_format({'bg_color': '#FEF9C3', 'border': 1, 'align': 'center'})

    # --- New: All Results Sheet (Everything) ---
    all_results_sheet = workbook.add_worksheet('All Results')
    all_results_sheet.hide() # Keep hidden as requested
    all_results_cols = ['Register No', 'Year', 'Dept', 'Scheme', 'Subject', 'Subject Name', 'Grade', 'SGPA']
    for i, col in enumerate(all_results_cols):
        all_results_sheet.write(0, i, col, fmt_table_header_blue)
    
    # Ensure all required columns exist in df
    if 'Scheme' not in df.columns:
        df['Scheme'] = 'Unknown'
    if 'Subject Name' not in df.columns:
        df['Subject Name'] = df['Subject']
    
    for i, row in df[all_results_cols].iterrows():
        for j, val in enumerate(row):
            all_results_sheet.write(i + 1, j, val, fmt_border)

    # Department Sheets
    for dept in stats.get('departments', []):
        sheet_name = dept[:31]
        sheet = workbook.add_worksheet(sheet_name)
        
        sheet.set_column(0, 0, 15) # Register No
        sheet.set_column(1, 1, 45) # Column B for Selection / Subject Name
        
        # Selection Dropdown
        sheet.write(8, 0, "SELECT SUBJECT:", fmt_table_header_blue)
        subj_list = ["Overall Department"] + sorted(list(stats.get('dept_sub_stats', {}).get(dept, {}).get(str(list(stats['dept_sub_stats'][dept].keys())[0]), {}).keys()))
        sheet.data_validation(8, 1, 8, 1, {'validate': 'list', 'source': subj_list})
        sheet.write(8, 1, "Overall Department", fmt_dropdown_box)

        # 1. Subject Key (AZ501)
        dept_clean_val = str(dept).strip().upper()
        sheet.write('AZ501', f'="{dept_clean_val}_" & UPPER($B$9)')

        # Metric Cards (Row 10-12)
        card_labels = ["Appeared", "Passed", "Failed", "Pass Rate", "Fail Rate"]
        card_formats = [fmt_card_val_blue, fmt_card_val_green, fmt_card_val_red, fmt_card_perc, fmt_card_perc]
        ranges = [(0, 3), (4, 7), (8, 10), (11, 13), (14, 15)]
        
        for i, r in enumerate(ranges):
            c1, c2 = r
            sheet.merge_range(10, c1, 10, c2, card_labels[i], fmt_card_title)
            vlookup_formula = f'=IFERROR(VLOOKUP($AZ$501, _DATA_!$A$2:$AZ${data_row_idx}, {i+2}, FALSE), 0)'
            sheet.merge_range(11, c1, 12, c2, vlookup_formula, card_formats[i])

        # Bridge Data
        G_BRIDGE, P_BRIDGE, COL_AZ, COL_BA = 505, 520, 51, 52
        for i, g in enumerate(grade_headers):
            val_cell = f"$BA${G_BRIDGE + i + 1}"
            tot_cell = f"$BA${P_BRIDGE + 1}"
            lbl_form = f'="{g} - " & TEXT({val_cell}/MAX({tot_cell}, 1), "0%")'
            sheet.write(G_BRIDGE + i, COL_AZ, lbl_form)
            sheet.write(G_BRIDGE + i, COL_BA, f'=IFERROR(VLOOKUP($AZ$501, _DATA_!$A$2:$AZ${data_row_idx}, {7+i}, FALSE), 0)')

        p_labels = ["Appeared", "Passed", "Failed"]
        for i, label in enumerate(p_labels):
            sheet.write(P_BRIDGE + i, COL_AZ, label)
            sheet.write(P_BRIDGE + i, COL_BA, f'=IFERROR(VLOOKUP($AZ$501, _DATA_!$A$2:$AZ${data_row_idx}, {2+i}, FALSE), 0)')

        # Charts
        grade_chart = workbook.add_chart({'type': 'doughnut'})
        grade_chart.add_series({
            'name': 'Grade Dist',
            'categories': [sheet_name, G_BRIDGE, COL_AZ, G_BRIDGE + len(grade_headers) - 1, COL_AZ],
            'values':     [sheet_name, G_BRIDGE, COL_BA, G_BRIDGE + len(grade_headers) - 1, COL_BA],
        })
        grade_chart.set_title({'name': 'Grade Distribution'})
        grade_chart.set_legend({'position': 'bottom', 'font': {'size': 9}})
        grade_chart.show_hidden_data() 
        sheet.insert_chart('A15', grade_chart, {'x_scale': 1.1, 'y_scale': 1.1})

        perf_chart = workbook.add_chart({'type': 'column'})
        perf_chart.add_series({
            'categories': [sheet_name, P_BRIDGE, COL_AZ, P_BRIDGE + 2, COL_AZ],
            'values':     [sheet_name, P_BRIDGE, COL_BA, P_BRIDGE + 2, COL_BA],
        })
        perf_chart.set_title({'name': 'Performance Overview'})
        perf_chart.set_legend({'none': True})
        perf_chart.show_hidden_data() 
        sheet.insert_chart('I15', perf_chart, {'x_scale': 1.1, 'y_scale': 1.1})

    workbook.close()
    print(f"Excel report generated: {output_path}")

if __name__ == "__main__":
    # Note: For running another laptop, ensure you have the PDF in the same folder 
    # or provide the correct path here.
    pdf_file = os.path.join(project_root, 'result_BMCs7.pdf')
    output_xlsx = os.path.join(project_root, 'Analysis_Report_BMCs7.xlsx')
    
    if os.path.exists(pdf_file):
        generate_excel_from_pdf(pdf_file, output_xlsx)
    else:
        print(f"Error: PDF file not found at {pdf_file}")
        print("Please ensure your PDF is in the project folder or update the file path in the script.")
