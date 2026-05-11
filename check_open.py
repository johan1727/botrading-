import sqlite3, glob

DB = 'tradesv3.dryrun.sqlite'
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("PRAGMA table_info(trades)")
cols = [r[1] for r in c.fetchall()]
print("Columnas:", cols)
profit_col = next((x for x in ['close_profit','profit_ratio','final_profit_ratio'] if x in cols), None)
reason_col = next((x for x in ['close_reason','exit_reason'] if x in cols), None)
close_col  = next((x for x in ['close_date','close_timestamp'] if x in cols), None)
print(f"Usando: profit={profit_col} reason={reason_col} close={close_col}")
c.execute(f"SELECT {profit_col}, {reason_col}, pair, open_date, {close_col} FROM trades WHERE is_open=0 ORDER BY {close_col}")
rows = c.fetchall()

total = len(rows)
wins = [r for r in rows if r[0] > 0]
losses = [r for r in rows if r[0] <= 0]
winrate = len(wins)/total*100 if total else 0
avg_win = sum(r[0] for r in wins)/len(wins)*100 if wins else 0
avg_loss = sum(r[0] for r in losses)/len(losses)*100 if losses else 0
total_profit = sum(r[0] for r in rows)*100

reasons = {}
for r in rows:
    reasons[r[1]] = reasons.get(r[1], 0) + 1

print(f"\n{'='*45}")
print(f"  WINRATE TOTAL: {winrate:.1f}%  ({len(wins)}W / {len(losses)}L / {total} trades)")
print(f"  Profit total:  {total_profit:+.2f}%")
print(f"  Avg ganancia:  +{avg_win:.2f}%")
print(f"  Avg pérdida:   {avg_loss:.2f}%")
print(f"{'='*45}")
print(f"\n  Motivos de salida:")
for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f"    {reason:<30} {count:>3} trades")

# Últimos 20 trades
print(f"\n  Últimos 10 trades:")
for r in rows[-10:]:
    sig = '+' if r[0]>0 else ''
    print(f"    {r[2]:<15} {sig}{r[0]*100:.2f}%  ({r[1]})")

# Por par — peores
print(f"\n  Por par (más de 2 trades):")
pairs = {}
for r in rows:
    p = r[2]
    if p not in pairs: pairs[p] = []
    pairs[p].append(r[0])
for p, profits in sorted(pairs.items(), key=lambda x: sum(x[1])):
    if len(profits) >= 2:
        wr = sum(1 for x in profits if x>0)/len(profits)*100
        total_p = sum(profits)*100
        print(f"    {p:<15} {wr:.0f}%WR  {total_p:+.2f}%  ({len(profits)} trades)")

conn.close()
