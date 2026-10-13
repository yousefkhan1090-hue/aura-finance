import os
import json
import base64
import sqlite3
import logging
import io
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from PIL import Image
from groq import Groq
import streamlit as st

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuraFinanceLuxury")

# Streamlit Page Configuration
st.set_page_config(
    page_title="Aura Finance Elite",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Luxury Dark Glassmorphism Theme & Custom CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
        background-color: #07090e;
        color: #f3f4f6;
    }
    
    .stApp {
        background: radial-gradient(circle at 50% -20%, #1e1b4b 0%, #07090e 80%);
    }

    /* Glassmorphic Cards */
    .glass-card {
        background: rgba(17, 24, 39, 0.6);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 18px;
        padding: 24px;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
        margin-bottom: 20px;
    }

    /* Gold / Indigo Gradients */
    .gold-title {
        background: linear-gradient(135deg, #fcd34d 0%, #f59e0b 50%, #d97706 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        text-align: center;
        font-size: 2.5rem;
    }

    /* Metric Cards Styling */
    div[data-testid="stMetric"] {
        background: rgba(17, 24, 39, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 16px;
        border-radius: 14px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    }
    div[data-testid="stMetric"] label {
        color: #94a3b8 !important;
        font-weight: 600;
    }

    /* Modern Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(17, 24, 39, 0.6);
        border-radius: 12px;
        padding: 10px 20px;
        color: #94a3b8;
        border: 1px solid rgba(255, 255, 255, 0.06);
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
    }

    /* Buttons */
    .stButton>button {
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 12px;
        padding: 10px 24px;
        font-weight: 600;
        box-shadow: 0 4px 20px rgba(79, 70, 229, 0.4);
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(79, 70, 229, 0.6);
    }
    </style>
""", unsafe_allow_html=True)

GROQ_API_KEY = "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"


# --- Data Models ---
@dataclass
class ReceiptItem:
    description: str
    quantity: int
    unit_price: float
    total_price: float

@dataclass
class ReceiptData:
    store_name: str
    date: str
    items: List[ReceiptItem]
    grand_total: float
    category: str = "Uncategorized"
    location_details: str = "In-Store / Direct"


# --- Database Service with Safe Schema Migration & Deletion Capabilities ---
class DatabaseService:
    def __init__(self, db_name: str = "aura_luxury.db"):
        self.db_name = db_name
        self._initialize_database()

    def _initialize_database(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_name TEXT,
                    purchase_date TEXT,
                    grand_total REAL,
                    category TEXT,
                    location_details TEXT DEFAULT 'In-Store / Direct',
                    entry_timestamp TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expense_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id INTEGER,
                    description TEXT,
                    quantity INTEGER,
                    unit_price REAL,
                    total_price REAL,
                    FOREIGN KEY (expense_id) REFERENCES expenses (id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT,
                    receive_date TEXT,
                    amount REAL,
                    category TEXT,
                    location_details TEXT DEFAULT 'Direct Deposit / Cash',
                    entry_timestamp TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Safe column migrations
            try:
                cursor.execute("ALTER TABLE expenses ADD COLUMN location_details TEXT DEFAULT 'In-Store / Direct'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE expenses ADD COLUMN entry_timestamp TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE incomes ADD COLUMN location_details TEXT DEFAULT 'Direct Deposit / Cash'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE incomes ADD COLUMN entry_timestamp TEXT")
            except sqlite3.OperationalError:
                pass

            conn.commit()

    def save_expense(self, data: ReceiptData) -> int:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO expenses (store_name, purchase_date, grand_total, category, location_details, entry_timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (data.store_name, data.date, data.grand_total, data.category, data.location_details, timestamp_str)
            )
            expense_id = cursor.lastrowid
            for item in data.items:
                cursor.execute(
                    "INSERT INTO expense_items (expense_id, description, quantity, unit_price, total_price) VALUES (?, ?, ?, ?, ?)",
                    (expense_id, item.description, item.quantity, item.unit_price, item.total_price)
                )
            conn.commit()
        return expense_id

    def save_income(self, source: str, date: str, amount: float, category: str, location: str):
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO incomes (source_name, receive_date, amount, category, location_details, entry_timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (source, date, amount, category, location, timestamp_str)
            )
            conn.commit()

    def delete_records(self, target_type: str, time_range: str) -> int:
        """Purges database records based on target type and time range."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        current_month_str = datetime.now().strftime("%Y-%m")
        current_year_str = datetime.now().strftime("%Y")

        deleted_count = 0
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()

            # Helper clause for filtering by date
            if time_range == "Today":
                exp_where = "WHERE purchase_date = ?"
                inc_where = "WHERE receive_date = ?"
                params = (today_str,)
            elif time_range == "Current Month":
                exp_where = "WHERE strftime('%Y-%m', purchase_date) = ?"
                inc_where = "WHERE strftime('%Y-%m', receive_date) = ?"
                params = (current_month_str,)
            elif time_range == "Current Year":
                exp_where = "WHERE strftime('%Y', purchase_date) = ?"
                inc_where = "WHERE strftime('%Y', receive_date) = ?"
                params = (current_year_str,)
            else:  # "All Time / Complete Reset"
                exp_where = ""
                inc_where = ""
                params = ()

            # Delete Expenses
            if target_type in ["Expenses Only", "All Records (Income & Expenses)"]:
                if exp_where:
                    cursor.execute(f"DELETE FROM expense_items WHERE expense_id IN (SELECT id FROM expenses {exp_where})", params)
                    cursor.execute(f"DELETE FROM expenses {exp_where}", params)
                else:
                    cursor.execute("DELETE FROM expense_items")
                    cursor.execute("DELETE FROM expenses")
                deleted_count += cursor.rowcount

            # Delete Incomes
            if target_type in ["Income Only", "All Records (Income & Expenses)"]:
                if inc_where:
                    cursor.execute(f"DELETE FROM incomes {inc_where}", params)
                else:
                    cursor.execute("DELETE FROM incomes")
                deleted_count += cursor.rowcount

            conn.commit()
        return deleted_count

    def get_comprehensive_analytics(self) -> Dict[str, Any]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        current_month_str = datetime.now().strftime("%Y-%m")

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(grand_total) FROM expenses WHERE purchase_date = ?", (today_str,))
            daily_expense = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT SUM(grand_total) FROM expenses WHERE strftime('%Y-%m', purchase_date) = ?", (current_month_str,))
            monthly_expense = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT SUM(amount) FROM incomes WHERE strftime('%Y-%m', receive_date) = ?", (current_month_str,))
            monthly_income = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT category, SUM(grand_total) FROM expenses GROUP BY category")
            expense_categories = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT id, entry_timestamp, store_name, category, location_details, grand_total FROM expenses ORDER BY id DESC")
            expense_records = [
                {
                    "Transaction ID": f"EXP-{r[0]:04d}",
                    "Date & Time": r[1] if r[1] else r[2],
                    "Place / Merchant Name": r[2],
                    "Type of Place / Category": r[3],
                    "Origin / Location": r[4] if r[4] else "In-Store",
                    "Amount Spent (DJF)": r[5]
                }
                for r in cursor.fetchall()
            ]

            cursor.execute("SELECT id, entry_timestamp, source_name, category, location_details, amount FROM incomes ORDER BY id DESC")
            income_records = [
                {
                    "Transaction ID": f"INC-{r[0]:04d}",
                    "Date & Time": r[1] if r[1] else r[2],
                    "Income Source Name": r[2],
                    "Source Type / Category": r[3],
                    "Received From / Method": r[4] if r[4] else "Direct Deposit",
                    "Amount Received (DJF)": r[5]
                }
                for r in cursor.fetchall()
            ]

        return {
            "daily_expense": daily_expense,
            "monthly_expense": monthly_expense,
            "monthly_income": monthly_income,
            "net_monthly": monthly_income - monthly_expense,
            "expense_categories": expense_categories,
            "expense_records": expense_records,
            "income_records": income_records
        }


# --- Groq AI Service ---
class GroqAIService:
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)

    def scan_receipt(self, image_bytes: bytes) -> ReceiptData:
        base64_img = base64.b64encode(image_bytes).decode('utf-8')
        prompt = (
            "Analyze this receipt image (which could be in any language). "
            "Extract details and return strictly as a valid JSON object with keys: "
            "\"store_name\" (string), \"date\" (string YYYY-MM-DD), "
            "\"items\" (list of objects with keys: \"description\", \"quantity\", \"unit_price\", \"total_price\"), "
            "\"grand_total\" (number in Djibouti Francs DJF), \"category\" (e.g., Groceries, Dining, Utilities, Entertainment, Shopping), "
            "and \"location_details\" (extracted city/address or store branch if visible, else 'Retail Branch'). "
            "Return raw JSON only, no markdown blocks."
        )

        completion = self.client.chat.completions.create(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            model="qwen/qwen3.8-27b",
        )
        cleaned_json = completion.choices[0].message.content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned_json)

        items = [
            ReceiptItem(
                description=i.get("description", "Item"),
                quantity=int(i.get("quantity", 1)),
                unit_price=float(i.get("unit_price", 0.0)),
                total_price=float(i.get("total_price", 0.0))
            )
            for i in parsed.get("items", [])
        ]

        return ReceiptData(
            store_name=parsed.get("store_name", "Unknown Store"),
            date=parsed.get("date", datetime.now().strftime("%Y-%m-%d")),
            items=items,
            grand_total=float(parsed.get("grand_total", 0.0)),
            category=parsed.get("category", "General"),
            location_details=parsed.get("location_details", "In-Store / Direct")
        )

    def transcribe_audio(self, audio_file_path: str) -> str:
        with open(audio_file_path, "rb") as file:
            transcription = self.client.audio.transcriptions.create(
                file=(audio_file_path, file.read()),
                model="whisper-large-v3",
                response_format="text"
            )
        return transcription

    def extract_entry_details(self, text: str) -> Tuple[str, float, str]:
        prompt = (
            f"Extract the name/source/merchant, numerical amount, and location/place origin from this phrase: '{text}'. "
            "Return strictly a JSON object with keys: \"name\" (string), \"amount\" (number), and \"location\" (string, e.g., 'City Mall', 'Online Transfer', 'Main Branch', etc.). "
            "If no location is mentioned, return 'Direct / Local'. If no amount is found, return 0.0. Raw JSON only, no markdown."
        )
        completion = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b"
        )
        cleaned = completion.choices[0].message.content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        return parsed.get("name", text), float(parsed.get("amount", 0.0)), parsed.get("location", "Direct / Local")

    def get_financial_advice(self, analytics_data: Dict[str, Any], user_query: str) -> str:
        system_prompt = (
            "You are an expert, professional, and empathetic personal finance manager assistant. "
            "Analyze the user's financial data in Djibouti Francs (DJF) and answer their query. "
            "CRITICAL RULE: The primary and ONLY currency used by the user is Djibouti Francs (DJF). Never convert currencies. "
            "You MUST reply in the exact same language that the user spoke in (English, French, or Urdu). "
            "Give clear, direct advice on savings, budgeting, and what expenses they should avoid or cut back on. "
            "Always state currency values in Djibouti Francs (DJF). "
            "Speak naturally like a friendly human companion, and use plenty of expressive emojis throughout your response! 😊💸"
        )
        user_prompt = f"Financial Data (in DJF): {json.dumps(analytics_data)}\n\nUser Question: {user_query}"

        completion = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="openai/gpt-oss-120b",
        )
        return completion.choices[0].message.content

    def get_proactive_insights(self, analytics_data: Dict[str, Any]) -> str:
        system_prompt = (
            "You are a proactive, sharp personal finance assistant. "
            "Analyze the user's financial data in Djibouti Francs (DJF). "
            "Notice notable spending trends, highest categories, or savings status. "
            "Give 1 or 2 friendly, direct observations or warnings that the user should notice right now. "
            "Keep it concise, supportive, and pack it with expressive emojis! 🧐💡"
        )
        user_prompt = f"Financial Data (in DJF): {json.dumps(analytics_data)}"

        completion = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="openai/gpt-oss-120b",
        )
        return completion.choices[0].message.content


# --- Initialize Services ---
db = DatabaseService()
groq_ai = GroqAIService(api_key=GROQ_API_KEY)


# --- Header ---
st.markdown("<h1 class='gold-title'>AURA FINANCE ELITE</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #94a3b8; margin-bottom: 30px;'>Enterprise Multilingual Expense, Income & AI Coach Suite (DJF Standard)</p>", unsafe_allow_html=True)

# --- Tabs Architecture ---
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 Executive Dashboard", 
    "🧾 AI Receipt Scanner", 
    "💰 Income Manager", 
    "✍️ Expense Entry", 
    "🗣️ Multilingual AI Coach", 
    "🎯 Budget & Excel Export",
    "🗑️ Data Management"
])


# --- TAB 1: DASHBOARD ---
with tab1:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("💎 Financial Overview")
    data = db.get_comprehensive_analytics()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Today's Expense", f"{data['daily_expense']:,.2f} DJF")
    with col2:
        st.metric("Monthly Income", f"{data['monthly_income']:,.2f} DJF")
    with col3:
        st.metric("Monthly Expense", f"{data['monthly_expense']:,.2f} DJF")
    with col4:
        st.metric("Net Savings", f"{data['net_monthly']:,.2f} DJF")

    st.markdown("###")
    
    st.markdown("#### 🔔 Proactive Assistant Notices")
    with st.spinner("Assistant is analyzing your recent cash flow..."):
        try:
            proactive_msg = groq_ai.get_proactive_insights(data)
            st.info(proactive_msg)
        except Exception as e:
            st.info("👋 Hey there! Add some income or expenses to let your assistant notice your spending habits! 💡")

    st.markdown("###")
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### Expense Categories")
        if data["expense_categories"]:
            st.bar_chart(data["expense_categories"])
        else:
            st.info("No expense data recorded yet.")
    with col_r:
        st.markdown("#### Recent Expenses Ledger")
        if data["expense_records"]:
            st.dataframe(pd.DataFrame(data["expense_records"]), use_container_width=True, hide_index=True)
        else:
            st.info("No recent expenses.")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 2: RECEIPT SCANNER ---
with tab2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("📸 Multilingual Vision Extraction")
    uploaded_receipt = st.file_uploader("Upload Receipt Photo", type=["jpg", "jpeg", "png"])

    if uploaded_receipt:
        col_img, col_res = st.columns(2)
        with col_img:
            st.image(uploaded_receipt, caption="Preview", use_container_width=True)
        with col_res:
            if st.button("🚀 Process Receipt with Vision AI"):
                with st.spinner("Analyzing receipt place, date, and items..."):
                    try:
                        file_bytes = uploaded_receipt.read()
                        receipt_data = groq_ai.scan_receipt(file_bytes)
                        db.save_expense(receipt_data)
                        st.success(f"Successfully logged receipt from **{receipt_data.store_name}** ({receipt_data.location_details}) for **{receipt_data.grand_total:,.2f} DJF**!")
                        
                        items_df = pd.DataFrame([
                            {"Description": i.description, "Qty": i.quantity, "Unit Price": f"{i.unit_price:,.2f} DJF", "Total": f"{i.total_price:,.2f} DJF"}
                            for i in receipt_data.items
                        ])
                        st.table(items_df)
                    except Exception as e:
                        st.error(f"Error: {e}")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 3: INCOME MANAGER ---
with tab3:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("💵 Income Entry (DJF)")
    
    col_inc_text, col_inc_voice = st.columns([1.2, 1])
    
    speech_inc_name = ""
    speech_inc_amt = 0.0
    speech_inc_loc = "Direct Deposit"
    
    with col_inc_voice:
        st.markdown("#### 🎙️ Speak Income Details")
        st.caption("Say something like: *'Salary 150000 DJF from Main Office'*")
        inc_voice_audio = st.audio_input("Record Voice", key="income_voice_recorder")
        if inc_voice_audio is not None:
            with st.spinner("Extracting source name, amount, and place..."):
                try:
                    temp_inc_path = "temp_inc_voice.wav"
                    with open(temp_inc_path, "wb") as f:
                        f.write(inc_voice_audio.getbuffer())
                    raw_text = groq_ai.transcribe_audio(temp_inc_path)
                    speech_inc_name, speech_inc_amt, speech_inc_loc = groq_ai.extract_entry_details(raw_text)
                    st.success(f"Extracted: **{speech_inc_name}** ({speech_inc_loc}) — **{speech_inc_amt:,.2f} DJF**")
                    if os.path.exists(temp_inc_path):
                        os.remove(temp_inc_path)
                except Exception as e:
                    st.error(f"Voice extraction error: {e}")

    with col_inc_text:
        with st.form("income_form"):
            inc_source = st.text_input("Payer / Source Name", value=speech_inc_name, placeholder="e.g., Corporate Salary")
            inc_location = st.text_input("Received From / Method / Place", value=speech_inc_loc, placeholder="e.g., Bank Transfer / Main Branch")
            inc_amount = st.number_input("Amount (DJF)", min_value=0.0, value=speech_inc_amt, format="%.2f", step=1000.0)
            inc_category = st.selectbox("Category", ["Salary", "Freelance / Business", "Investments", "Gifts", "Other Income"])
            
            submitted_inc = st.form_submit_button("💾 Log Income Entry")
            if submitted_inc:
                if inc_source and inc_amount > 0:
                    db.save_income(inc_source, datetime.now().strftime("%Y-%m-%d"), inc_amount, inc_category, inc_location)
                    st.success(f"Logged income of **{inc_amount:,.2f} DJF** from **{inc_source}** ({inc_location})!")
                else:
                    st.warning("Please enter a valid source and amount.")

    st.markdown("#### Income Ledger")
    data_inc = db.get_comprehensive_analytics()
    if data_inc["income_records"]:
        st.dataframe(pd.DataFrame(data_inc["income_records"]), use_container_width=True, hide_index=True)
    else:
        st.info("No income records found.")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 4: EXPENSE ENTRY ---
with tab4:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("💳 Quick Expense Entry (DJF)")
    
    col_exp_text, col_exp_voice = st.columns([1.2, 1])
    
    speech_exp_store = ""
    speech_exp_amt = 0.0
    speech_exp_loc = "In-Store / Local"
    
    with col_exp_voice:
        st.markdown("#### 🎙️ Speak Expense Details")
        st.caption("Say something like: *'Supermarket 5000 DJF at City Center Mall'*")
        exp_voice_audio = st.audio_input("Record Voice", key="expense_voice_recorder")
        if exp_voice_audio is not None:
            with st.spinner("Extracting store, place location, and amount..."):
                try:
                    temp_exp_path = "temp_exp_voice.wav"
                    with open(temp_exp_path, "wb") as f:
                        f.write(exp_voice_audio.getbuffer())
                    raw_text = groq_ai.transcribe_audio(temp_exp_path)
                    speech_exp_store, speech_exp_amt, speech_exp_loc = groq_ai.extract_entry_details(raw_text)
                    st.success(f"Extracted: **{speech_exp_store}** ({speech_exp_loc}) — **{speech_exp_amt:,.2f} DJF**")
                    if os.path.exists(temp_exp_path):
                        os.remove(temp_exp_path)
                except Exception as e:
                    st.error(f"Voice extraction error: {e}")

    with col_exp_text:
        with st.form("manual_entry_form"):
            exp_store = st.text_input("Merchant / Store / Place Name", value=speech_exp_store, placeholder="e.g., Grand Market")
            exp_location = st.text_input("Place / Branch / Location", value=speech_exp_loc, placeholder="e.g., Downtown Branch / Online")
            exp_amount = st.number_input("Grand Total (DJF)", min_value=0.0, value=speech_exp_amt, format="%.2f", step=100.0)
            exp_category = st.selectbox("Type of Place / Category", ["Groceries", "Dining", "Utilities", "Entertainment", "Shopping", "Transport", "General"])
            
            submitted_exp = st.form_submit_button("💾 Log Expense Entry")
            if submitted_exp:
                if exp_store and exp_amount > 0:
                    manual_receipt = ReceiptData(
                        store_name=exp_store,
                        date=datetime.now().strftime("%Y-%m-%d"),
                        items=[ReceiptItem(description="Manual Entry", quantity=1, unit_price=exp_amount, total_price=exp_amount)],
                        grand_total=exp_amount,
                        category=exp_category,
                        location_details=exp_location
                    )
                    db.save_expense(manual_receipt)
                    st.success(f"Logged expense of **{exp_amount:,.2f} DJF** under **{exp_category}** for **{exp_store}** ({exp_location}).")
                else:
                    st.warning("Please enter a valid store and amount.")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 5: MULTILINGUAL AI COACH ---
with tab5:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("🎙️ Multilingual Voice AI Financial Companion")
    st.markdown("Speak in **English**, **French**, or **Urdu**. The coach will respond in the exact same language.")
    
    audio_value = st.audio_input("Record Audio Question")

    if audio_value is not None:
        st.audio(audio_value)
        if st.button("✨ Consult AI Coach"):
            with st.spinner("Processing voice request..."):
                try:
                    audio_path = "temp_voice.wav"
                    with open(audio_path, "wb") as f:
                        f.write(audio_value.getbuffer())

                    user_query = groq_ai.transcribe_audio(audio_path)
                    st.markdown(f"**🗣️ You asked:** *\"{user_query}\"*")

                    analytics = db.get_comprehensive_analytics()
                    ai_response = groq_ai.get_financial_advice(analytics, user_query)

                    st.markdown("### 🤖 Coach Response")
                    st.success(ai_response)

                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                except Exception as e:
                    st.error(f"Error: {e}")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 6: BUDGET & EXCEL EXPORT ---
with tab6:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("📈 Monthly Budgeting & Excel Reports")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.markdown("#### Budget Limit Check")
        budget_limit = st.number_input("Monthly Spending Limit (DJF)", min_value=1000.0, value=50000.0, step=5000.0)
        analytics = db.get_comprehensive_analytics()
        spent = analytics["monthly_expense"]
        
        progress = min(spent / budget_limit, 1.0)
        st.progress(progress)
        st.write(f"Spent **{spent:,.2f} DJF** out of **{budget_limit:,.2f} DJF** limit.")
        
        if spent > budget_limit:
            st.error("🚨 Over Budget!")
        else:
            st.success("✨ Within Budget!")

    with col_b2:
        st.markdown("#### Export Executive Excel Workbook")
        st.write("Generates a structured multi-sheet Excel file (`.xlsx`) detailing exact transaction dates/times, place names, location origins, amounts, and categories.")
        if st.button("📥 Generate Professional Excel (.xlsx)"):
            try:
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_exp = pd.DataFrame(analytics["expense_records"]) if analytics["expense_records"] else pd.DataFrame(columns=["Transaction ID", "Date & Time", "Place / Merchant Name", "Type of Place / Category", "Origin / Location", "Amount Spent (DJF)"])
                    df_inc = pd.DataFrame(analytics["income_records"]) if analytics["income_records"] else pd.DataFrame(columns=["Transaction ID", "Date & Time", "Income Source Name", "Source Type / Category", "Received From / Method", "Amount Received (DJF)"])
                    
                    df_inc.to_excel(writer, sheet_name='Income Ledger', index=False)
                    df_exp.to_excel(writer, sheet_name='Expense Ledger', index=False)
                
                excel_data = output.getvalue()
                st.download_button(
                    label="📥 Download Professional Excel File",
                    data=excel_data,
                    file_name=f"aura_finance_executive_report_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                st.success("Executive Excel report generated successfully with full detail headers!")
            except Exception as e:
                st.error(f"Error: {e}")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 7: DATA MANAGEMENT & CLEANUP ---
with tab7:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("🗑️ Professional Data Purge & Management")
    st.write("Manage your database by selectively clearing past transactions by time period and record category.")

    col_del1, col_del2 = st.columns(2)

    with col_del1:
        st.markdown("#### Select Filter Parameters")
        target_type = st.selectbox(
            "Select Record Type to Delete",
            ["Expenses Only", "Income Only", "All Records (Income & Expenses)"]
        )
        time_range = st.selectbox(
            "Select Time Period",
            ["Today", "Current Month", "Current Year", "All Time / Complete Reset"]
        )

    with col_del2:
        st.markdown("#### Confirmation & Execution")
        st.warning(f"⚠️ Warning: This action will permanently remove **{target_type}** for **{time_range}**.")
        confirm_toggle = st.checkbox("I understand and confirm that this action cannot be undone.")

        if st.button("🚨 Execute Selected Data Purge"):
            if confirm_toggle:
                rows_removed = db.delete_records(target_type, time_range)
                st.success(f"🎉 Cleanup completed! Successfully deleted **{rows_removed}** record(s) from the database.")
                st.rerun()
            else:
                st.error("Please check the confirmation box before executing the purge.")

    st.markdown('</div>', unsafe_allow_html=True)
