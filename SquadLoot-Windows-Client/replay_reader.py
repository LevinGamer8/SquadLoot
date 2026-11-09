"""Read only the aggregate JSON that Fortnite ChestCounter already generated.

We never open the game's memory or its live network stream.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def _as_dict(v):
    return v if isinstance(v, dict) else {}


def _as_list(v):
    return v if isinstance(v, list) else []


def _num(v):
    try:
        return max(0,int(v or 0))
    except (ValueError,TypeError):
        return 0


def _text(v,default='',max_chars=130):
    return str(v).strip()[:max_chars] if v is not None else default


def match_to_payload(m, client_id):
    """Normalize PascalCase C# JSON. Team-shared loot is deliberately NOT double counted."""
    if not isinstance(m,dict) or m.get('IsBattleRoyale') is False:
        return None
    name=_text(m.get('PlayerName'),max_chars=60)
    if not name:
        return None
    replay=_text(m.get('ReplayFile'),max_chars=130)
    started=_text(m.get('MatchStartUtc') or m.get('AnalyzedAtUtc'),max_chars=50)
    sid=_text(m.get('SessionId'),max_chars=180)
    if not sid:
        sid=hashlib.sha256((name+'|'+replay+'|'+started).encode()).hexdigest()
    raw_chests=_as_list(m.get('Chests'))
    interactions=_as_list(m.get('LootInteractions'))
    other=_as_dict(m.get('OtherInteractions'))
    kinds={}
    for c in raw_chests:
        if isinstance(c,dict):
            key=_text(c.get('Kind') or 'Sonstige Truhe',max_chars=80)
            kinds[key]=kinds.get(key,0)+1
    for k,v in other.items():
        key=_text(k,max_chars=80)
        kinds[key]=kinds.get(key,0)+_num(v)
    destroyed=sum(bool(c.get('Destroyed')) for c in raw_chests if isinstance(c,dict))
    reopened=sum(bool(c.get('Reopened')) and bool(c.get('IsChest')) for c in interactions if isinstance(c,dict))
    # Our patched build records individual interactions; older official versions may not.
    if not reopened:
        reopened=sum(bool(c.get('Reopened')) for c in raw_chests if isinstance(c,dict))
    ammo=_num(m.get('AmmoBoxesOpened'))
    food=_num(other.get('Caisse de nourriture') or other.get('Food box') or other.get('FoodBox'))
    other_total=_num(m.get('OtherContainersOpened'))
    own_treasures=[t for t in _as_list(m.get('TreasureFinds')) if isinstance(t,dict)]
    treasure_names=[_text(t.get('DisplayName') or t.get('Item') or t.get('PrizeId') or 'Unbekannt',max_chars=110) for t in own_treasures]
    account=_text(m.get('EpicId') or name,max_chars=95)
    # Send a stable pseudonymous identifier instead of the raw Epic account identifier.
    account_hash=hashlib.sha256(('squadloot-epic:'+account).encode()).hexdigest()[:32]
    return {
        'client_id':client_id,'session_id':sid,'replay_file':replay,
        'name':name,'account_id':account_hash,'started':started,
        'mode':_text(m.get('Playlist'),max_chars=115),'chests':_num(m.get('ChestsOpened')),
        'destroyed':destroyed,'reopened':reopened,'ammo':ammo,'food':food,
        'other':max(0,other_total-food),'treasure_count':len(own_treasures),
        'treasure_names':treasure_names[:20],'kinds':kinds,
    }


def load_matches(path, client_id):
    file=Path(path)
    if not file.is_file():
        return []
    obj=json.loads(file.read_text(encoding='utf-8-sig'))
    out=[]
    for m in _as_list(_as_dict(obj).get('Matches')):
        row=match_to_payload(m,client_id)
        if row is not None:
            out.append(row)
    return out


def fingerprint(row):
    """Allows modified/re-analyzed replays to replace previous server values safely."""
    blob=json.dumps({k:v for k,v in row.items() if k!='round_id'},sort_keys=True,ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()
