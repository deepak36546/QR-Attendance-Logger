import pandas as pd
import sqlite3
from datetime import datetime, timedelta

def get_dashboard_analytics(today_date):
    conn = sqlite3.connect('database.db')
    
    # 1. Top KPI Cards
    total_students = pd.read_sql("SELECT COUNT(*) as count FROM users WHERE role='student'", conn).iloc[0]['count']
    
    active_classes_df = pd.read_sql("SELECT COUNT(DISTINCT sub_id) as count FROM attendance_logs WHERE date(timestamp) = ?", conn, params=(today_date,))
    active_classes = active_classes_df.iloc[0]['count']
    
    # Calculate Today's Average Attendance %
    today_logs = pd.read_sql("SELECT status FROM attendance_logs WHERE date(timestamp) = ?", conn, params=(today_date,))
    if not today_logs.empty and total_students > 0 and active_classes > 0:
        total_expected_scans = total_students * active_classes
        present_count = len(today_logs[today_logs['status'] == 'PRESENT'])
        today_avg = round((present_count / total_expected_scans) * 100, 1)
    else:
        today_avg = 0.0

    kpis = {
        'total_students': int(total_students),
        'active_classes': int(active_classes),
        'today_avg': today_avg
    }

    # 2. At-Risk Prediction Widget (< 75%)
    all_logs = pd.read_sql("""
        SELECT a.student_id, u.username, a.sub_id, date(a.timestamp) as date, a.status 
        FROM attendance_logs a JOIN users u ON a.student_id = u.user_id
    """, conn)
    
    at_risk_list = []
    if not all_logs.empty:
        total_classes = all_logs.groupby('sub_id')['date'].nunique().reset_index()
        total_classes.rename(columns={'date': 'total_sessions'}, inplace=True)
        
        present_logs = all_logs[all_logs['status'] == 'PRESENT']
        student_attendance = present_logs.groupby(['student_id', 'username', 'sub_id']).size().reset_index(name='attended')
        
        merged_df = pd.merge(student_attendance, total_classes, on='sub_id')
        merged_df['percentage'] = (merged_df['attended'] / merged_df['total_sessions']) * 100
        
        at_risk_df = merged_df[merged_df['percentage'] < 75.0]
        at_risk_list = at_risk_df.to_dict('records')

    # 3. Subject-wise Distribution (Bar Chart Data)
    subject_chart = {'labels': [], 'data': []}
    if not all_logs.empty:
        subj_grouped = all_logs[all_logs['status'] == 'PRESENT'].groupby('sub_id').size().reset_index(name='count')
        subject_chart['labels'] = subj_grouped['sub_id'].tolist()
        subject_chart['data'] = subj_grouped['count'].tolist()

    # 4. Attendance Trend (Line Chart - Last 7 Days)
    trend_chart = {'labels': [], 'data': []}
    if not all_logs.empty:
        past_7_days = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
        trend_df = all_logs[all_logs['date'].isin(past_7_days)]
        if not trend_df.empty:
            daily_present = trend_df[trend_df['status'] == 'PRESENT'].groupby('date').size()
            for day in past_7_days:
                trend_chart['labels'].append(day[-5:]) # Show MM-DD
                trend_chart['data'].append(int(daily_present.get(day, 0)))

    conn.close()
    return kpis, at_risk_list, subject_chart, trend_chart

def get_student_profile(student_id):
    conn = sqlite3.connect('database.db')
    df = pd.read_sql("SELECT status FROM attendance_logs WHERE student_id=?", conn, params=(student_id,))
    conn.close()
    
    if df.empty: return 0
    total = len(df)
    present = len(df[df['status'] == 'PRESENT'])
    return int((present / total) * 100)