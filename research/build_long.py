"""Download a 2009-2026 daily panel (O/C/V) for the NASDAQ universe + ETFs, float32, saved as parquet."""
import os, time, numpy as np, pandas as pd, yfinance as yf, warnings; warnings.filterwarnings("ignore")
W = os.environ.get("PANEL_DIR", "/home/user/work"); os.makedirs(W, exist_ok=True)
t0 = time.time()
u = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'universe_nasdaq.csv')); tick = sorted({str(t).replace('/', '-').strip() for t in u.symbol.dropna() if str(t).isascii()})
O, C, V = {}, {}, {}
for i in range(0, len(tick), 100):
    b = tick[i:i + 100]
    for a in range(3):
        try:
            d = yf.download(b, start="2009-06-01", interval='1d', group_by='ticker', threads=True, progress=False, auto_adjust=True); break
        except Exception as e:
            print('retry', i, e, flush=True); time.sleep(10)
    for t in b:
        try:
            x = d[t]
            if x['Close'].notna().sum() < 250: continue
            O[t] = x['Open'].astype('float32'); C[t] = x['Close'].astype('float32'); V[t] = x['Volume'].astype('float32')
        except Exception: pass
    del d
    print(f'  {i + len(b)}/{len(tick)} {time.time() - t0:.0f}s', flush=True)
O, C, V = pd.DataFrame(O), pd.DataFrame(C), pd.DataFrame(V)
O.to_parquet(f'{W}/long_O.parquet'); C.to_parquet(f'{W}/long_C.parquet'); V.to_parquet(f'{W}/long_V.parquet')
e = yf.download(['QQQ', 'TQQQ', 'QLD', 'SPY', '^VIX'], start="2009-06-01", interval='1d', group_by='ticker', progress=False, auto_adjust=True)
e.to_pickle(f'{W}/long_etf.pkl')
print('panel', C.shape, C.index[0].date(), C.index[-1].date(), f'{time.time() - t0:.0f}s')
