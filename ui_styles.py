"""
ui_styles.py
Custom CSS theme for AI Scanner Trader: white background, orange / purple / black accents.
"""

CUSTOM_CSS = """
<style>
    .stApp {
        background-color: #FFFFFF;
        color: #1a1a1a;
    }
    section[data-testid="stSidebar"] {
        background-color: #6A0DAD;
        color: #FFFFFF;
    }
    section[data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    h1, h2, h3 {
        color: #6A0DAD;
        font-weight: 700;
    }
    .stButton>button {
        background-color: #FF8C00;
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 0.5em 1.2em;
    }
    .stButton>button:hover {
        background-color: #6A0DAD;
        color: #FFFFFF;
    }
    div[data-testid="stMetric"] {
        background-color: #FAF5FF;
        border: 1px solid #6A0DAD;
        border-radius: 10px;
        padding: 10px;
    }
    .signal-card-buy {
        background-color: #FFF4E6;
        border-left: 6px solid #FF8C00;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
        color: #1a1a1a;
    }
    .signal-card-sell {
        background-color: #F3E8FF;
        border-left: 6px solid #6A0DAD;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
        color: #1a1a1a;
    }
    .signal-card-notrade {
        background-color: #F5F5F5;
        border-left: 6px solid #1a1a1a;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
        color: #1a1a1a;
    }
    .badge-buy { color: #FFFFFF; background-color: #FF8C00; padding: 3px 10px; border-radius: 12px; font-weight:700; }
    .badge-sell { color: #FFFFFF; background-color: #6A0DAD; padding: 3px 10px; border-radius: 12px; font-weight:700; }
    .badge-notrade { color: #FFFFFF; background-color: #555555; padding: 3px 10px; border-radius: 12px; font-weight:700; }
</style>
"""
