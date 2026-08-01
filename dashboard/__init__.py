"""
dashboard — שתי אפליקציות ה-Streamlit מעל לוג השיחות האנונימי (storage/).

    streamlit run dashboard/app.py --server.port 8501     # סקירה, פורט 8501
    streamlit run dashboard/ml_app.py --server.port 8502  # חיזוי, פורט 8502

שכבת הנתונים (data.py, pandas טהור) ושכבת התצוגה המשותפת (ui.py — פלטה,
CSS, גרפים, בורר קובץ הלוג והמסננים) מופרדות מהעמודים עצמם, ונבדקות
אופליין בסוללת הבדיקות בלי להרים שרת.
"""
