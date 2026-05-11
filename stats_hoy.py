import sqlite3
from datetime import datetime, date

conn = sqlite3.connect('tradesv3.dryrun.sqlite')
c = conn.cursor()

hoy = date.today().strftime('%Y-%m-%d')
c.execute(f"SELECT pair, open_date, close_date, close_profit, exit_reason FROM trades WHERE open_date >= '{hoy}' ORDER BY open_date")
rows = c.fetchall()

abiertos = [r for r in rows if not r[2]]
cerrados = [r for r in rows if r[2]]
wins = [r for r in cerrados if r[3] and r[3] > 0]
losses = [r for r in cerrados if r[3] and r[3] <= 0]

print(f"\nTrades HOY ({hoy}): {len(rows)} total")
print(f"  Cerrados: {len(cerrados)}  |  Abiertos: {len(abiertos)}")
if cerrados:
    wr = len(wins)/len(cerrados)*100
    print(f"  WR hoy: {wr:.0f}%  ({len(wins)}W / {len(losses)}L)")
    avg_win = sum(r[3] for r in wins)/len(wins)*100 if wins else 0
    avg_loss = sum(r[3] for r in losses)/len(losses)*100 if losses else 0
    total = sum(r[3] for r in cerrados)*100
    print(f"  Profit neto hoy: {total:+.2f}%  |  avg W: +{avg_win:.2f}%  avg L: {avg_loss:.2f}%")
    # Proyeccion con $60
    ganancia_usd = sum(r[3] for r in cerrados) * 60 * 0.20
    print(f"  Ganancia en $60: ${ganancia_usd:+.3f}")

print(f"\nDetalle:")
for r in rows:
    estado = 'ABIERTO' if not r[2] else ('WIN +' if r[3] and r[3]>0 else 'LOSS')
    profit = f'{r[3]*100:+.2f}%' if r[3] else '...'
    hora = r[1][11:16] if r[1] else ''
    print(f"  {hora}  {r[0]:<15} {profit:<10} {estado}  {r[4] or ''}")

# Trades por hora
print(f"\nTrades por hora hoy:")
from collections import Counter
horas = Counter(r[1][11:13] for r in rows if r[1])
for h, n in sorted(horas.items()):
    print(f"  {h}:00  {'█'*n} {n}")

conn.close()
