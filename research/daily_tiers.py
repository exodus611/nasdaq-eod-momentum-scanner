"""Quick test: which EVERY-DAY top-2 rule is least bad on a 48h horizon (entry next open, exit close of the session after entry)."""
import time, sys, numpy as np, pandas as pd, yfinance as yf
t0 = time.time()
u = pd.read_csv('data/universe_nasdaq.csv'); tick = sorted({str(t).replace('/', '-').strip() for t in u.symbol.dropna() if str(t).isascii()})
O, C, V = {}, {}, {}
for i in range(0, len(tick), 150):
    b = tick[i:i + 150]
    for a in range(3):
        try:
            d = yf.download(b, period='10y', interval='1d', group_by='ticker', threads=True, progress=False, auto_adjust=True); break
        except Exception as e:
            print('retry', i, e); time.sleep(10)
    for t in b:
        try:
            x = d[t]
            if x['Close'].notna().sum() < 250: continue
            O[t] = x['Open'].astype('float32'); C[t] = x['Close'].astype('float32'); V[t] = x['Volume'].astype('float32')
        except Exception: pass
    print(f'  {i + len(b)}/{len(tick)} {time.time() - t0:.0f}s', flush=True)
O, C, V = pd.DataFrame(O), pd.DataFrame(C), pd.DataFrame(V)
q = yf.download('QQQ', period='10y', interval='1d', progress=False, auto_adjust=True)
qc = q['Close'].squeeze(); qc = qc.reindex(C.index)
print('panel', C.shape, C.index[0].date(), C.index[-1].date(), f'{time.time() - t0:.0f}s')
O.to_parquet('research/data/panel_O.parquet'); C.to_parquet('research/data/panel_C.parquet'); V.to_parquet('research/data/panel_V.parquet'); qc.to_frame('QQQ').to_parquet('research/data/panel_Q.parquet')

def rsi2(x):
    d = x.diff(); up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); dn = (-d).clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

ret1 = C / C.shift(1) - 1; ret5 = C / C.shift(5) - 1
sma200 = C.rolling(200).mean(); sma10 = C.rolling(10).mean()
dv21 = (C * V).shift(1).rolling(21).mean()
srsi = C.apply(rsi2)
ll20 = C.shift(1).rolling(20).min()
o1 = O.shift(-1); c2 = C.shift(-2)
r = (c2 / o1 - 1 - 0.0015).astype('float32')           # net trade return, next open -> close of T+2
q_rsi = rsi2(qc); q_ret = qc / qc.shift(1) - 1
base = (C > sma200) & (dv21 >= 2e7) & (C >= 5)
qr = q_rsi.values[:, None]
rules = {
 'A  QQQ RSI2 < 10': base & (ret1 <= -0.03) & (qr < 10),
 'B1 10 <= RSI2 < 20': base & (ret1 <= -0.03) & (qr >= 10) & (qr < 20),
 'B2 20 <= RSI2 < 30': base & (ret1 <= -0.03) & (qr >= 20) & (qr < 30),
 'B  10 <= RSI2 < 30': base & (ret1 <= -0.03) & (qr >= 10) & (qr < 30),
 'C1 30 <= RSI2 < 50': base & (ret1 <= -0.03) & (qr >= 30) & (qr < 50),
 'C2 50 <= RSI2 < 70': base & (ret1 <= -0.03) & (qr >= 50) & (qr < 70),
 'C3 RSI2 >= 70': base & (ret1 <= -0.03) & (qr >= 70),
 'C  RSI2 >= 30': base & (ret1 <= -0.03) & (qr >= 30),
 'ALL every day': base & (ret1 <= -0.03),
}
TOP = 2
def evaluate(mask):
    m = mask & r.notna() & dv21.notna()
    rows = []
    dvv = dv21.where(m)
    for day in m.index[m.any(axis=1)]:
        s = dvv.loc[day].dropna().sort_values(ascending=False).head(TOP)
        for t in s.index: rows.append((day, t, float(r.at[day, t])))
    return pd.DataFrame(rows, columns=['date', 'ticker', 'r'])
out = []
for name, mask in rules.items():
    tr = evaluate(mask)
    if len(tr) == 0: continue
    tr['year'] = tr.date.dt.year
    yr = tr.groupby('year').r.sum()
    sub = lambda a, b: tr[(tr.year >= a) & (tr.year <= b)].r
    out.append(dict(rule=name, trades=len(tr), days=tr.date.nunique(), per_yr=round(len(tr) / (len(C) / 252)), mean_bp=round(tr.r.mean() * 1e4), med_bp=round(tr.r.median() * 1e4),
                    hit=round((tr.r > 0).mean() * 100), yrs_pos=f"{(yr > 0).sum()}/{yr.size}", sum_pct_10=round(tr.r.sum() * 10, 1),
                    mean_16_20=round(sub(2016, 2020).mean() * 1e4), mean_21_26=round(sub(2021, 2026).mean() * 1e4), worst_yr=round(yr.min() * 10, 1)))
    print(' '.join(f'{y}:{v*1e4/len(tr[tr.year==y]):+.0f}' for y,v in yr.items()))
    print(f"{name[:70]:<70} n={len(tr):5d} mean={tr.r.mean() * 1e4:+5.0f}bp med={tr.r.median() * 1e4:+4.0f} hit={(tr.r > 0).mean() * 100:.0f}% yrs+={(yr > 0).sum()}/{yr.size}  16-20 {sub(2016, 2020).mean() * 1e4:+.0f}  21-26 {sub(2021, 2026).mean() * 1e4:+.0f}  P&L@10%/name={tr.r.sum() * 10:+.1f}%", flush=True)
    tr.to_csv(f"research/data/daily_{name.split()[0]}.csv", index=False)
pd.DataFrame(out).to_csv('research/data/daily_rules.csv', index=False)
print(f'done {time.time() - t0:.0f}s')
