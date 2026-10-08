import re
import sqlite3
import ollama
import pandas as pd
import streamlit as st

MODEL = "llama3.2"
DB = "weather.db"

SCHEMA = """Table: weather_hourly
Columns:
- timestamp TEXT, format 'YYYY-MM-DD HH:MM:SS', one row per hour, about the last 8 days
- temp_f REAL, temperature in Fahrenheit
- humidity_pct REAL, relative humidity percent
- wind_mph REAL, wind speed in mph"""

EXAMPLES = """Examples:
Q: What was the highest temperature?
SQL: SELECT MAX(temp_f) AS max_temp_f FROM weather_hourly
Q: What is the average humidity per day?
SQL: SELECT date(timestamp) AS day, ROUND(AVG(humidity_pct), 1) AS avg_humidity FROM weather_hourly GROUP BY day ORDER BY day
Q: Which hour was the windiest?
SQL: SELECT timestamp, wind_mph FROM weather_hourly ORDER BY wind_mph DESC LIMIT 1
Q: How many hours was it below freezing?
SQL: SELECT COUNT(*) AS freezing_hours FROM weather_hourly WHERE temp_f < 32"""

SYSTEM = ("You convert questions into a single SQLite SELECT query.\n"
          f"{SCHEMA}\n{EXAMPLES}\n"
          "Reply with ONLY the SQL query. No explanation, no markdown.")

def question_to_sql(question):
    resp = ollama.chat(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": question}],
        options={"temperature": 0})
    return extract_sql(resp["message"]["content"])

def extract_sql(text):
    text = re.sub(r"```(?:sql)?", "", text, flags=re.I)
    m = re.search(r"select\b.*", text, flags=re.I | re.S)
    if not m:
        return ""
    sql = m.group(0).split(";")[0]      # keep only the first statement
    return sql.split("\n\n")[0].strip()  # drop trailing explanation

def is_safe(sql):
    s = sql.strip().rstrip(";").lower()
    banned = r"\b(insert|update|delete|drop|alter|create|attach|pragma|replace)\b"
    return s.startswith("select") and ";" not in s and not re.search(banned, s)

def run_query(sql):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)  # read-only connection
    try:
        return pd.read_sql(f"SELECT * FROM ({sql}) LIMIT 200", conn)
    finally:
        conn.close()

st.title("Ask the Weather Data")
st.caption(f"Runs locally with Ollama ({MODEL}). Generated SQL is shown below each answer.")
question = st.text_input("Ask a question, e.g. 'What was the hottest hour?'")

if st.button("Ask") and question:
    try:
        sql = question_to_sql(question)
    except Exception as e:
        st.error(f"Could not reach Ollama. Is it running? ({e})")
        st.stop()
    if not sql:
        st.error("The model did not return a SELECT query. Try rephrasing.")
    else:
        st.code(sql, language="sql")
        if not is_safe(sql):
            st.error("Blocked: only a single SELECT query is allowed.")
        else:
            try:
                st.dataframe(run_query(sql))
            except Exception as e:
                st.error(f"Query failed: {e}")