"""Timestamped market snapshots and automatic directions for saved simulations."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import urllib.parse
import urllib.request


def numeric(value):
    try:
        result=float(value)
        return result if value is not None and value != '' and math.isfinite(result) else None
    except (TypeError,ValueError):
        return None


def probabilities(hist, line, spread=False):
    # Histograms contain away-minus-home margin or combined total.
    win=push=count=0
    for value,n in hist:
        result=value+line if spread else value-line
        count+=n
        win+=n if result>0 else 0
        push+=n if result==0 else 0
    return {'win':round(win/count,5),'push':round(push/count,5),
            'lose':round((count-win-push)/count,5)} if count else None


def normalize_line(raw, fetched_at):
    return {'provider':str(raw.get('provider') or 'Unnamed provider'),
            'homeSpread':numeric(raw.get('spread')),'total':numeric(raw.get('overUnder')),
            'awayMoneyline':numeric(raw.get('awayMoneyline')),
            'homeMoneyline':numeric(raw.get('homeMoneyline')),
            'formattedSpread':raw.get('formattedSpread'), 'fetchedAt':fetched_at,
            'source':'CollegeFootballData /lines', 'period':'full'}


def refresh_lines(games, now, data_dir, allow_fetch):
    path=Path(data_dir)/'simulator'/'market-cache.json'
    cache=json.loads(path.read_text()) if path.exists() else {'games':{}}
    issues=[]
    token=os.environ.get('CFBD_API_KEY')
    if allow_fetch and token:
        weeks=sorted({int(g['week']) for g in games})
        for week in weeks:
            query=urllib.parse.urlencode({'year':2026,'week':week,'seasonType':'regular'})
            try:
                req=urllib.request.Request('https://api.collegefootballdata.com/lines?'+query,
                                           headers={'Authorization':'Bearer '+token})
                with urllib.request.urlopen(req,timeout=90) as response:
                    rows=json.load(response)
                if not isinstance(rows,list):
                    raise ValueError('invalid lines response')
                captured=now.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
                for row in rows:
                    cache['games'][str(row['id'])]=[normalize_line(line,captured) for line in row.get('lines',[])]
            except Exception as exc:
                issues.append(f'Week {week}: market-line refresh failed ({type(exc).__name__})')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(cache,separators=(',',':'),allow_nan=False))
    elif not cache['games']:
        issues.append('Market lines have not been fetched in this environment.')
    return cache['games'],issues


def choose_market(lines):
    # One coherent provider snapshot, never cherry-pick spread and total across books.
    usable=[line for line in lines if line['homeSpread'] is not None or line['total'] is not None]
    return min(usable,key=lambda line:(
        -int(line['homeSpread'] is not None)-int(line['total'] is not None),
        0 if line['provider'].lower()=='consensus' else 1,
        line['provider'].lower())) if usable else None


def directions(simulation, away, home, market):
    if simulation.get('status')!='ready':
        return {}
    outputs={}
    for period,p in simulation['periods'].items():
        winner='away' if p['awayWin']>p['homeWin'] else 'home' if p['homeWin']>p['awayWin'] else None
        out={'winner':{'side':winner,'team':away if winner=='away' else home if winner=='home' else None,
                       'probability':max(p['awayWin'],p['homeWin'])},
             'projectedHomeSpread':round(p['away']['mean']-p['home']['mean'],2),
             'projectedTotal':p['total']['mean']}
        if period=='full' and market:
            spread=market['homeSpread']
            total=market['total']
            if spread is not None:
                prob=probabilities(p['marginHist'],-spread,True)
                side='away' if prob['win']>prob['lose'] else 'home' if prob['lose']>prob['win'] else None
                out['spread']={'side':side,'team':away if side=='away' else home if side=='home' else None,
                               'line':-spread if side=='away' else spread if side=='home' else None,
                               'probability':max(prob['win'],prob['lose']),'pushProbability':prob['push'],
                               'homeLine':spread}
            if total is not None:
                prob=probabilities(p['totalHist'],total)
                side='over' if prob['win']>prob['lose'] else 'under' if prob['lose']>prob['win'] else None
                out['total']={'side':side,'line':total,'probability':max(prob['win'],prob['lose']),
                              'pushProbability':prob['push']}
        outputs[period]=out
    return outputs


def grade_directions(forecast, actual):
    predictions=forecast.get('directions',{}).get('full',{})
    away=actual['awayPoints'];home=actual['homePoints']
    outcomes={}
    for key,pred in predictions.items():
        if key not in ('winner','spread','total') or not pred.get('side'):
            continue
        if key=='winner':
            result=away-home if pred['side']=='away' else home-away
        elif key=='spread':
            result=(away-home if pred['side']=='away' else home-away)+pred['line']
        else:
            result=(away+home-pred['line'])*(1 if pred['side']=='over' else -1)
        outcomes[key]='win' if result>0 else 'loss' if result<0 else 'push'
    return outcomes
