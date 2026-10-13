import os
import json
import base64
import sqlite3
import logging
import io
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any
from PIL import Image
from groq import Groq
import gradio as gr

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuraFinanceGradio")

# Hardcoded Groq API Key
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


# --- Database Service (Expenses & Income in DJF) ---
class DatabaseService:
    def __init__(self, db_name: str = "aura_finance.db"):
        self.db_name = db_name
        self._initialize_database()

    def _initialize_database(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # Expenses Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store_name TEXT,
                    purchase_date TEXT,
                    grand_total REAL,
                    category TEXT,
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
            # Income Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT,
                    receive_date TEXT,
                    amount REAL,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def save_expense(self, data: ReceiptData) -> int:
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO expenses (store_name, purchase_date, grand_total, category) VALUES (?, ?, ?, ?)",
                (data.store_name, data.date, data.grand_total, data.category)
            )
            expense_id = cursor.lastrowid
            for item in data.items:
                cursor.execute(
                    "INSERT INTO expense_items (expense_id, description, quantity, unit_price, total_price) VALUES (?, ?, ?, ?, ?)",
                    (expense_id, item.description, item.quantity, item.unit_price, item.total_price)
                )
            conn.commit()
        return expense_id

    def save_income(self, source: str, date: str, amount: float, category: str):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO incomes (source_name, receive_date, amount, category) VALUES (?, ?, ?, ?)",
                (source, date, amount, category)
            )
            conn.commit()

    def get_comprehensive_analytics(self) -> Dict[str, Any]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        current_month_str = datetime.now().strftime("%Y-%m")
        current_year_str = datetime.now().strftime("%Y")

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()

            # Expenses Totals
            cursor.execute("SELECT SUM(grand_total) FROM expenses WHERE purchase_date = ?", (today_str,))
            daily_expense = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT SUM(grand_total) FROM expenses WHERE strftime('%Y-%m', purchase_date) = ?", (current_month_str,))
            monthly_expense = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT SUM(grand_total) FROM expenses WHERE strftime('%Y', purchase_date) = ?", (current_year_str,))
            yearly_expense = cursor.fetchone()[0] or 0.0

            # Income Totals
            cursor.execute("SELECT SUM(amount) FROM incomes WHERE strftime('%Y-%m', receive_date) = ?", (current_month_str,))
            monthly_income = cursor.fetchone()[0] or 0.0

            cursor.execute("SELECT SUM(amount) FROM incomes WHERE strftime('%Y', receive_date) = ?", (current_year_str,))
            yearly_income = cursor.fetchone()[0] or 0.0

            # Category Breakdown
            cursor.execute("SELECT category, SUM(grand_total) FROM expenses GROUP BY category")
            expense_categories = {row[0]: row[1] for row in cursor.fetchall()}

            # Records for tables
            cursor.execute("SELECT id, store_name, purchase_date, grand_total, category FROM expenses ORDER BY id DESC")
            expense_records = [{"ID": r[0], "Store/Merchant": r[1], "Date": r[2], "Amount (DJF)": r[3], "Category": r[4]} for r in cursor.fetchall()]

            cursor.execute("SELECT id, source_name, receive_date, amount, category FROM incomes ORDER BY id DESC")
            income_records = [{"ID": r[0], "Income Source": r[1], "Date": r[2], "Amount (DJF)": r[3], "Category": r[4]} for r in cursor.fetchall()]

        return {
            "daily_expense": daily_expense,
            "monthly_expense": monthly_expense,
            "yearly_expense": yearly_expense,
            "monthly_income": monthly_income,
            "yearly_income": yearly_income,
            "net_monthly": monthly_income - monthly_expense,
            "expense_categories": expense_categories,
            "expense_records": expense_records,
            "income_records": income_records
        }


# --- Groq AI Service ---
class GroqAIService:
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)

    def scan_receipt(self, image_path: str) -> tuple:
        if not image_path:
            return "Please upload an image first.", pd.DataFrame()
        
        with open(image_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')

        prompt = (
            "Analyze this receipt image (which could be in any language). "
            "Extract details and return strictly as a valid JSON object with keys: "
            "\"store_name\" (string), \"date\" (string YYYY-MM-DD), "
            "\"items\" (list of objects with keys: \"description\", \"quantity\", \"unit_price\", \"total_price\"), "
            "\"grand_total\" (number in Djibouti Francs DJF), and \"category\" (e.g., Groceries, Dining, Utilities, Entertainment, Shopping). "
            "Return raw JSON only, no markdown blocks."
        )

        try:
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

            receipt_data = ReceiptData(
                store_name=parsed.get("store_name", "Unknown Store"),
                date=parsed.get("date", datetime.now().strftime("%Y-%m-%d")),
                items=items,
                grand_total=float(parsed.get("grand_total", 0.0)),
                category=parsed.get("category", "General")
            )

            db.save_expense(receipt_data)

            msg = f"🎉 Success! Processed receipt from **{receipt_data.store_name}** for **{receipt_data.grand_total:,.2f} DJF** under **{receipt_data.category}**. Saved securely! 🛒✅"
            
            items_df = pd.DataFrame([
                {"Description": i.description, "Qty": i.quantity, "Unit Price": f"{i.unit_price:,.2f} DJF", "Total": f"{i.total_price:,.2f} DJF"}
                for i in receipt_data.items
            ])
            return msg, items_df
        except Exception as e:
            return f"❌ Error scanning receipt: {str(e)}", pd.DataFrame()

    def voice_coach_chat(self, audio_file) -> str:
        if not audio_file:
            return "🎙️ Please record an audio message first!"
        
        try:
            with open(audio_file, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(audio_file, file.read()),
                    model="whisper-large-v3",
                    response_format="text"
                )
            
            analytics = db.get_comprehensive_analytics()
            
            system_prompt = (
                "You are an expert, professional, and empathetic personal finance manager assistant. "
                "Analyze the user's comprehensive financial data (income, expenses, net savings in Djibouti Francs DJF, and categories) "
                "and answer their query. "
                "CRITICAL RULE: The primary and ONLY currency used by the user is Djibouti Francs (DJF). Never convert currencies. "
                "You MUST reply in the exact same language that the user spoke in (English, French, or Urdu). "
                "Give clear, direct advice on savings, budgeting, and what expenses they should avoid or cut back on. "
                "Always state currency values in Djibouti Francs (DJF). "
                "Speak naturally like a friendly human companion, and use plenty of expressive emojis throughout your response! 😊💸"
            )
            user_prompt = f"Financial Data (in DJF): {json.dumps(analytics)}\n\nUser Question: {transcription}"

            completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="openai/gpt-oss-120b",
            )
            
            response_text = f"**🗣️ You asked:** *\"{transcription}\"*\n\n**🤖 Coach Response:**\n{completion.choices[0].message.content}"
            return response_text
        except Exception as e:
            return f"❌ Voice processing error: {str(e)}"


# --- Initialize Services ---
db = DatabaseService()
groq_ai = GroqAIService(api_key=GROQ_API_KEY)


# --- Build Gradio Interface ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 💳 Aura Finance Assistant")
    gr.Markdown("Your sleek, multilingual AI companion for managing income, expenses, and budgeting in Djibouti Francs (DJF)! 🚀 (Supports English, Français, Urdu)")

    with gr.Tabs():
        # TAB 1: DASHBOARD
        with gr.Tab("📊 Dashboard"):
            gr.Markdown("### Financial Performance Overview")
            refresh_btn = gr.Button("🔄 Refresh Analytics", variant="secondary")
            
            with gr.Row():
                daily_metric = gr.Number(label="📅 Today's Expense (DJF)", interactive=False)
                monthly_inc_metric = gr.Number(label="🗓️ Monthly Income (DJF)", interactive=False)
                monthly_exp_metric = gr.Number(label="📉 Monthly Expense (DJF)", interactive=False)
                net_metric = gr.Number(label="💎 Net Monthly Savings (DJF)", interactive=False)

            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Recent Expenses Ledger")
                    expense_table = gr.Dataframe(interactive=False)
                with gr.Column():
                    gr.Markdown("### Recent Income Ledger")
                    income_table = gr.Dataframe(interactive=False)

            def update_dashboard():
                data = db.get_comprehensive_analytics()
                return (
                    data["daily_expense"],
                    data["monthly_income"],
                    data["monthly_expense"],
                    data["net_monthly"],
                    pd.DataFrame(data["expense_records"]),
                    pd.DataFrame(data["income_records"])
                )

            refresh_btn.click(
                fn=update_dashboard,
                outputs=[daily_metric, monthly_inc_metric, monthly_exp_metric, net_metric, expense_table, income_table]
            )

        # TAB 2: RECEIPT SCANNER
        with gr.Tab("🧾 Receipt Scanner"):
            gr.Markdown("### Multilingual AI Receipt Scanner (DJF)")
            with gr.Row():
                receipt_img = gr.Image(type="filepath", label="Upload Receipt Image")
                with gr.Column():
                    scan_output_msg = gr.Markdown()
                    line_items_table = gr.Dataframe(label="Extracted Line Items")
            
            scan_btn = gr.Button("🚀 Run AI Scan & Log", variant="primary")
            scan_btn.click(fn=groq_ai.scan_receipt, inputs=receipt_img, outputs=[scan_output_msg, line_items_table])

        # TAB 3: INCOME MANAGER
        with gr.Tab("💰 Income Manager"):
            gr.Markdown("### Record Income Source (DJF)")
            with gr.Row():
                inc_source = gr.Textbox(label="Income Source / Payer", placeholder="e.g., Company Salary 🏢")
                inc_amount = gr.Number(label="Amount (DJF)", value=0.0)
                inc_category = gr.Dropdown(choices=["Salary", "Freelance / Business", "Investments", "Gifts", "Other Income"], label="Category", value="Salary")
            
            inc_btn = gr.Button("💾 Save Income Record", variant="primary")
            inc_status = gr.Markdown()

            def handle_save_income(source, amount, cat):
                if not source or amount <= 0:
                    return "⚠️ Please provide a valid source and amount greater than 0."
                date_str = datetime.now().strftime("%Y-%m-%d")
                db.save_income(source, date_str, amount, cat)
                return f"🎉 Successfully saved {amount:,.2f} DJF from {source}!"

            inc_btn.click(fn=handle_save_income, inputs=[inc_source, inc_amount, inc_category], outputs=inc_status)

        # TAB 4: MANUAL EXPENSE ENTRY
        with gr.Tab("✍️ Expense Entry"):
            gr.Markdown("### Quick Manual Expense Entry (DJF)")
            with gr.Row():
                exp_store = gr.Textbox(label="Store / Merchant Name", placeholder="e.g., Supermarket 🛒")
                exp_amount = gr.Number(label="Grand Total (DJF)", value=0.0)
                exp_category = gr.Dropdown(choices=["Groceries", "Dining", "Utilities", "Entertainment", "Shopping", "Transport", "General"], label="Category", value="Groceries")
            
            exp_btn = gr.Button("💾 Save Expense Record", variant="primary")
            exp_status = gr.Markdown()

            def handle_save_expense(store, amount, cat):
                if not store or amount <= 0:
                    return "⚠️ Please provide a valid store name and amount greater than 0."
                date_str = datetime.now().strftime("%Y-%m-%d")
                manual_receipt = ReceiptData(
                    store_name=store,
                    date=date_str,
                    items=[ReceiptItem(description="Manual Entry", quantity=1, unit_price=amount, total_price=amount)],
                    grand_total=amount,
                    category=cat
                )
                db.save_expense(manual_receipt)
                return f"🎉 Successfully logged {amount:,.2f} DJF under {cat} for {store}!"

            exp_btn.click(fn=handle_save_expense, inputs=[exp_store, exp_amount, exp_category], outputs=exp_status)

        # TAB 5: VOICE AI COACH
        with gr.Tab("🗣️ Voice AI Coach"):
            gr.Markdown("### Multilingual Voice AI Coach (English, Français, اردو)")
            gr.Markdown("Record your voice message below. The coach will understand and reply back in your exact language with human warmth and emojis! ✨")
            
            audio_input = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Record Your Question")
            coach_btn = gr.Button("✨ Chat with Coach", variant="primary")
            coach_output = gr.Markdown()

            coach_btn.click(fn=groq_ai.voice_coach_chat, inputs=audio_input, outputs=coach_output)

        # TAB 6: BUDGET & EXCEL EXPORT
        with gr.Tab("🎯 Budget & Excel Export"):
            gr.Markdown("### Budget Targets & Professional Excel Export")
            
            with gr.Row():
                with gr.Column():
                    gr.Markdown("#### Monthly Budget Goal")
                    budget_input = gr.Number(label="Monthly Spending Limit (DJF)", value=50000.0)
                    check_budget_btn = gr.Button("Check Budget Status")
                    budget_status = gr.Markdown()

                    def evaluate_budget(limit):
                        analytics = db.get_comprehensive_analytics()
                        spent = analytics["monthly_expense"]
                        if spent > limit:
                            return f"🚨 **Alert**: You've spent {spent:,.2f} DJF out of your {limit:,.2f} DJF limit. You are over budget! 💪"
                        else:
                            return f"✨ **Looking Great**: You've spent {spent:,.2f} DJF out of your {limit:,.2f} DJF limit. You're within budget! 👍"

                    check_budget_btn.click(fn=evaluate_budget, inputs=budget_input, outputs=budget_status)

                with gr.Column():
                    gr.Markdown("#### Excel Workbook Export")
                    export_btn = gr.Button("📥 Generate Professional Excel Report", variant="primary")
                    excel_file = gr.File(label="Download Excel File (.xlsx)")

                    def generate_excel():
                        analytics = db.get_comprehensive_analytics()
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df_exp = pd.DataFrame(analytics["expense_records"]) if analytics["expense_records"] else pd.DataFrame(columns=["ID", "Store/Merchant", "Date", "Amount (DJF)", "Category"])
                            df_inc = pd.DataFrame(analytics["income_records"]) if analytics["income_records"] else pd.DataFrame(columns=["ID", "Income Source", "Date", "Amount (DJF)", "Category"])
                            
                            df_inc.to_excel(writer, sheet_name='Income Ledger', index=False)
                            df_exp.to_excel(writer, sheet_name='Expense Ledger', index=False)
                        
                        file_path = f"aura_finance_report_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
                        with open(file_path, "wb") as f:
                            f.write(output.getvalue())
                        return file_path

                    export_btn.click(fn=generate_excel, outputs=excel_file)

# Run app and create public link easily
if __name__ == "__main__":
    demo.launch(share=True)