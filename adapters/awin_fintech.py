"""Legacy AwinFinTech dashboard adapter extracted from DAIO core.

This adapter is opt-in. It reads project evidence only and must not become a
second task/work authority.
"""
import json
from datetime import datetime

CATEGORIES={
 "🪙 核心指數與 ETF 權值":["0050.TW","006208.TW","00692.TW","00635U.TW","00981A.TW","00403A.TW","2330.TW","2308.TW","2454.TW","2317.TW","2382.TW","2376.TW","2383.TW"],
 "💎 高價與 IC 設計龍頭":["3034.TW","3443.TW","3661.TW","3008.TW","2408.TW","2337.TW","2344.TW","3231.TW","3293.TWO","3450.TW","3529.TWO","3533.TW","3711.TW","6488.TWO","6531.TW","6669.TW","6789.TW","8046.TW","8069.TWO","8299.TWO"],
 "🚢 航運與原物料傳產":["2603.TW","2609.TW","2615.TW","1234.TW","1432.TW","1815.TWO"],
 "🏦 金融與租賃控股":["2881.TW","2882.TW","2884.TW","2886.TW","2891.TW","5871.TW","5876.TW"],
 "🌐 美股 AI 科技巨頭":["NVDA","TSLA","AAPL","MSFT","AMD"]}

def _market(root):
    p=root/"data"/"watchlist_data_fetch_log.json"
    if not p.exists(): return {}
    data=json.loads(p.read_text(encoding="utf-8"))
    results={r["symbol"]:r.get("timeframes",{}) for r in data.get("results",[])}
    cats=[]
    for name,syms in CATEGORIES.items():
        items=[]
        for s in syms:
            items.append({"symbol":s,"timeframes":results.get(s,{}),
                          "db":s.lower().replace(".","_")+".db","status":"PERSISTED"})
        cats.append({"category":name,"count":len(items),"items":items})
    return {"fetched_at":data.get("fetched_at",datetime.now().isoformat()),
            "total_symbols":data.get("total",len(results)),
            "database_engine":"SQLite 3 (data/db/*.db)",
            "schema_version":"v2 (timestamp, open, high, low, close, volume, available_at)",
            "categories":cats}

def _replay(root):
    p=root/"data"/"change045_case001_rts_a_replay.json"
    if not p.exists(): return {}
    data=json.loads(p.read_text(encoding="utf-8"))
    # Preserve evidence from the actual replay artifact rather than inventing defaults.
    return {"source":"data/change045_case001_rts_a_replay.json","data":data}

def collect_sections(project_root):
    return {"market_data_inventory":_market(project_root),
            "blind_replay_matrix":_replay(project_root)}
