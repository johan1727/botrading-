import sqlite3

import glob, os
dbs = glob.glob('user_data/*.sqlite') + glob.glob('user_data/**/*.sqlite')
print("DBs encontradas:", dbs)
db_path = dbs[0] if dbs else 'user_data/tradesv3.sqlite'
print("Usando:", db_path)
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tablas:", tables)

if 'trades' in tables:
    cur.execute("""SELECT pair, close_profit_abs, close_profit, close_date, exit_reason 
                   FROM trades WHERE is_open=0 ORDER BY close_date DESC LIMIT 30""")
    trades = cur.fetchall()
    wins = sum(1 for t in trades if t[1] and t[1] > 0)
    losses = sum(1 for t in trades if t[1] and t[1] <= 0)
    total_profit = sum(t[1] for t in trades if t[1])
    wr = wins/(wins+losses)*100 if (wins+losses) > 0 else 0
    print(f"\nTrades cerrados: {len(trades)} | Wins: {wins} | Losses: {losses} | WR: {wr:.0f}% | Profit: {total_profit:+.4f} USDT\n")
    for t in trades:
        icon = "✅" if t[1] and t[1] > 0 else "❌"
        print(f"{icon} {str(t[0]):15s} | {t[1]:+.4f} USDT ({t[2]*100:+.2f}%) | {t[4]} | {t[3]}")
else:
    print("No hay tabla trades - buscando alternativa...")
    for table in tables:
        cur.execute(f"SELECT * FROM {table} LIMIT 2")
        cols = [d[0] for d in cur.description]
        print(f"  {table}: {cols}")

conn.close()
