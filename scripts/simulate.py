#!/usr/bin/env python3
"""Empirical Monte Carlo baseline. No fitted-to-results accuracy claims.

Only completed, already-started games enter a forecast. Quarter vectors are
sampled together, preserving within-game dependence; score increments are
scaled to shrunk offense/opponent-defense means. This is NOT play-by-play AI.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from functools import lru_cache

import numpy as np

VERSION = 'cfb-empirical-v1.0.1'
RUNS = 10000
ROOT = Path(__file__).resolve().parents[1]


def stamp(dt):
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def date(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False))
    temp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def completed(g, cutoff):
    return (g.get('completed') is True and date(g['startDate']) < cutoff
            and all(isinstance(g.get(s + 'Points'), (int, float)) for s in ('away', 'home')))


def has_quarters(g):
    return all(isinstance(g.get(s + 'LineScores'), list)
               and len(g[s + 'LineScores']) >= 4
               and all(isinstance(v, (int, float)) and v >= 0 for v in g[s + 'LineScores'])
               for s in ('away', 'home'))


def weights(rows, location=None):
    # Explicit baseline choices, not parameters optimized on this season's results.
    # Last five games receive more weight; location is a mild preference.
    n = len(rows)
    w = np.array([0.85 ** (n - i - 1) for i in range(n)])
    if location:
        w *= [1.25 if r[2] == location else 1 for r in rows]
    return w / w.sum()


def history(games, team, cutoff):
    rows = []
    for g in sorted(games, key=lambda x: x['startDate']):
        if not completed(g, cutoff) or not has_quarters(g):
            continue
        if team not in (g['awayTeam'], g['homeTeam']):
            continue
        s = 'away' if g['awayTeam'] == team else 'home'
        o = 'home' if s == 'away' else 'away'
        # Overtime is kept separate from regulation quarters.
        rows.append((g[s + 'LineScores'][:4], g[o + 'LineScores'][:4],
                     'neutral' if g.get('neutralSite') else s, g['id']))
    return rows


def distribution(values):
    vals, counts = np.unique(values, return_counts=True)
    return [[int(v), int(n)] for v, n in zip(vals, counts)]


def summary(values):
    return {'mean': round(float(np.mean(values)), 2),
            'median': round(float(np.median(values)), 2),
            'p10': round(float(np.quantile(values, .1)), 2),
            'p90': round(float(np.quantile(values, .9)), 2)}


@lru_cache(maxsize=2)
def adjusted_rates(encoded_games):
    """Ridge team offense/defense fit using ONLY the eligible score history.

    Each observed team-quarter score has an offense term, opponent-defense term,
    and venue term. Four observations of shrinkage keep sparse teams near league
    scoring. Quarter means are fit together with the same design matrix.
    """
    games = json.loads(encoded_games)
    teams = sorted({g[s+'Team'] for g in games for s in ('away','home')})
    index = {t:i for i,t in enumerate(teams)}
    n = len(teams)
    design = np.zeros((2*len(games),2*n+2))
    y = np.zeros((2*len(games),4))
    for i,g in enumerate(games):
        for j,(side,opp) in enumerate((('away','home'),('home','away'))):
            row=2*i+j
            design[row,0]=1
            design[row,1+index[g[side+'Team']]]=1
            design[row,1+n+index[g[opp+'Team']]]=1
            design[row,-1]=0 if g.get('neutralSite') else (-.5 if side=='away' else .5)
            y[row]=g[side+'LineScores'][:4]
    penalty=np.eye(design.shape[1])*4
    penalty[0,0]=.000001
    beta=np.linalg.solve(design.T@design+penalty,design.T@y)
    return index,beta


def simulate_game(g, games, cutoff, runs=RUNS):
    eligible = [x for x in games if completed(x, cutoff) and has_quarters(x)
                and (x.get('homeClassification') == 'fbs' or x.get('awayClassification') == 'fbs')]
    away = history(games, g['awayTeam'], cutoff)
    home = history(games, g['homeTeam'], cutoff)
    if not away or not home or len(eligible) < 10:
        return {'status': 'insufficient_history', 'awayGames': len(away), 'homeGames': len(home)}
    seed = int(digest([VERSION, g['id'], eligible, away, home])[:16], 16)
    rng = np.random.default_rng(seed)
    # League prior consists of paired home/away quarter vectors, in both orientations.
    league = np.array([[x['awayLineScores'][:4], x['homeLineScores'][:4]] for x in eligible], float)
    prior = league.mean(axis=(0, 1))
    wa = weights(away, None if g.get('neutralSite') else 'away')
    wh = weights(home, None if g.get('neutralSite') else 'home')
    a = np.array([[r[0], r[1]] for r in away], float)
    h = np.array([[r[0], r[1]] for r in home], float)
    am = np.average(a, axis=0, weights=wa)
    hm = np.average(h, axis=0, weights=wh)
    # Four-game league prior protects small samples. No current aggregate stats,
    # postgame Elo, or future results enter this calculation.
    am = (am * len(a) + prior * 4) / (len(a) + 4)
    hm = (hm * len(h) + prior * 4) / (len(h) + 4)
    index,beta=adjusted_rates(json.dumps(eligible,sort_keys=True))
    nt=len(index)
    targets=[]
    for side,opp in (('away','home'),('home','away')):
        venue=0 if g.get('neutralSite') else (-.5 if side=='away' else .5)
        # A team absent from eligible FBS history falls back to the league prior.
        attack=beta[1+index[g[side+'Team']]] if g[side+'Team'] in index else 0
        defense=beta[1+nt+index[g[opp+'Team']]] if g[opp+'Team'] in index else 0
        targets.append(np.maximum(0,beta[0]+attack+defense+venue*beta[-1]))
    target=np.array(targets)
    # Half away-team history, half home-team history, with a four-game prior.
    mix = np.concatenate((a, h[:, ::-1], league, league[:, ::-1]))
    strength = (len(a) + len(h)) / (len(a) + len(h) + 8)
    probs = np.concatenate((wa * strength / 2, wh * strength / 2,
                            np.full(len(league) * 2, (1-strength) / (2*len(league)))))
    raw_mean = np.average(mix, axis=0, weights=probs)
    sampled = mix[rng.choice(len(mix), size=runs, p=probs)]
    scaled = sampled * np.divide(target, raw_mean, out=np.ones_like(target), where=raw_mean > 0)
    quarters = np.floor(scaled + rng.random(scaled.shape)).astype(int)
    # Resolve regulation ties with actual historical overtime pairs where available.
    overtime = []
    for x in eligible:
        ao = x['awayPoints'] - sum(x['awayLineScores'][:4])
        ho = x['homePoints'] - sum(x['homeLineScores'][:4])
        if sum(x['awayLineScores'][:4]) == sum(x['homeLineScores'][:4]) and ao != ho:
            overtime.extend(((ao, ho), (ho, ao)))
    full = quarters.sum(axis=2)
    tied = full[:, 0] == full[:, 1]
    if overtime and tied.any():
        full[tied] += np.array(overtime)[rng.integers(len(overtime), size=int(tied.sum()))]
    periods = {}
    for name, scores in [('q1', quarters[:, :, 0]), ('h1', quarters[:, :, :2].sum(axis=2)), ('full', full)]:
        av, hv = scores[:, 0], scores[:, 1]
        periods[name] = {'away': summary(av), 'home': summary(hv), 'total': summary(av+hv),
                         'awayWin': round(float(np.mean(av > hv)), 5),
                         'homeWin': round(float(np.mean(hv > av)), 5),
                         'tie': round(float(np.mean(av == hv)), 5),
                         'marginHist': distribution(av-hv), 'totalHist': distribution(av+hv),
                         'awayHist': distribution(av), 'homeHist': distribution(hv)}
    return {'status': 'ready', 'runs': runs, 'seed': str(seed), 'awayGames': len(a),
            'homeGames': len(h), 'leagueGames': len(eligible), 'periods': periods,
            'meanModel': 'Ridge offense/opponent-defense quarter scoring with venue term; four-observation shrinkage'}


STAT_MAP = {
    'passing': {'YDS': 'passYards', 'TD': 'passTD', 'INT': 'interceptions'},
    'rushing': {'CAR': 'rushAttempts', 'ATT': 'rushAttempts', 'YDS': 'rushYards', 'TD': 'rushTD'},
    'receiving': {'REC': 'receptions', 'YDS': 'recYards', 'TD': 'recTD'},
}


def parse_players(boxes):
    records = {}
    for box in boxes:
        for team in box.get('teams', []):
            for cat in team.get('categories', []):
                category = cat['name'].lower()
                if category not in STAT_MAP:
                    continue
                for typ in cat.get('types', []):
                    label = typ['name'].upper().strip()
                    field = STAT_MAP[category].get(label)
                    for athlete in typ.get('athletes', []):
                        if athlete.get('name', '').strip().lower() in ('team', 'team stats', 'totals', ''):
                            continue  # Kneel-down/team totals are not individual athletes.
                        key = (str(box['id']), team['team'], str(athlete['id']))
                        row = records.setdefault(key, {'name': athlete['name'], 'stats': {}})
                        try:
                            raw = str(athlete['stat']).replace(',', '')
                            if category == 'passing' and label in ('C/ATT', 'CMP/ATT', 'CP/ATT'):
                                c, a = map(float, raw.split('/'))
                                row['stats'].update(completions=c, passAttempts=a)
                            elif field:
                                row['stats'][field] = float(raw)
                        except (ValueError, TypeError):
                            continue
    return {k: v for k, v in records.items() if v['stats']}


def simulate_players(g, games, records, cutoff, runs=RUNS):
    result = []
    for team in (g['awayTeam'], g['homeTeam']):
        team_games = sorted([x for x in games if completed(x, cutoff)
                             and team in (x['awayTeam'], x['homeTeam'])], key=lambda x: x['startDate'])
        # A missing box score is NOT a zero game. Only covered team games are used.
        covered = {gid for gid, t, _ in records if t == team}
        team_games = [x for x in team_games if str(x['id']) in covered]
        if not team_games:
            continue
        ids = {pid for gid, t, pid in records if t == team and gid in {str(x['id']) for x in team_games}}
        for pid in sorted(ids):
            appearances = [(x, records[(str(x['id']), team, pid)]) for x in team_games
                           if (str(x['id']), team, pid) in records]
            if not appearances:
                continue
            first_date = appearances[0][0]['startDate']
            recent = [x for x in team_games if x['startDate'] >= first_date][-5:]
            if not any((str(x['id']), team, pid) in records for x in recent[-2:]):
                continue
            fields = sorted({f for x in recent for f in records.get((str(x['id']), team, pid), {}).get('stats', {})})
            vector = np.array([[records.get((str(x['id']), team, pid), {}).get('stats', {}).get(f, 0)
                                for f in fields] for x in recent])
            rng = np.random.default_rng(int(digest([VERSION, g['id'], team, pid, vector.tolist()])[:16], 16))
            w = np.array([.8 ** (len(recent)-i-1) for i in range(len(recent))]); w /= w.sum()
            samples = vector[rng.choice(len(vector), size=runs, p=w)]
            stats = {f: {**summary(samples[:, i]), 'hist': distribution(samples[:, i])} for i, f in enumerate(fields)}
            result.append({'id': pid, 'name': appearances[-1][1]['name'], 'team': team,
                           'sampleGames': len(recent), 'lastSeen': appearances[-1][0]['startDate'],
                           'inLatestBox': appearances[-1][0]['id'] == team_games[-1]['id'],
                           'availability': 'Unverified; historical role baseline', 'stats': stats})
    return sorted(result, key=lambda x: (x['team'], -max((v['mean'] for v in x['stats'].values()), default=0)))


def refresh_boxes(games, now, data_dir):
    token = os.environ.get('CFBD_API_KEY')
    cache = data_dir / 'player-boxes'
    cache.mkdir(parents=True, exist_ok=True)
    issues = []
    weeks = sorted({int(x['week']) for x in games if completed(x, now)
                    and (x.get('homeClassification') == 'fbs' or x.get('awayClassification') == 'fbs')})
    for week in weeks:
        path = cache / f'2026-{week}.json'
        done_ids = {str(x['id']) for x in games if x['week'] == week and completed(x, now)
                    and (x.get('homeClassification') == 'fbs' or x.get('awayClassification') == 'fbs')}
        old = load(path, {'games': [], 'coveredIds': []})
        # Revisit the latest week for stat corrections; old weeks only for new finals.
        if token and (week == max(weeks) or not done_ids.issubset(set(old.get('coveredIds', [])))):
            url = 'https://api.collegefootballdata.com/games/players?' + urllib.parse.urlencode(
                {'year': 2026, 'week': week, 'seasonType': 'regular', 'classification': 'fbs'})
            try:
                req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
                with urllib.request.urlopen(req, timeout=90) as response:
                    boxes = json.load(response)
                if not isinstance(boxes, list) or not boxes:
                    raise ValueError('empty/non-list response')
                save(path, {'fetchedAt': stamp(now), 'coveredIds': [str(x['id']) for x in boxes], 'games': boxes})
            except Exception as exc:
                # Never log headers or credentials.
                issues.append(f'Week {week}: box-score refresh failed ({type(exc).__name__})')
        elif not token and not path.exists():
            issues.append(f'Week {week}: player box scores not connected in this environment')
    all_boxes = []
    for path in sorted(cache.glob('2026-*.json')):
        all_boxes.extend(load(path, {}).get('games', []))
    return parse_players(all_boxes), issues


def grade(forecast, actual, player_records):
    if date(forecast['generatedAt']) >= date(actual['startDate']):
        return None  # Never grade forecasts made after kickoff as pregame predictions.
    out = {'gameId': actual['id'], 'forecastAt': forecast['generatedAt'], 'periods': {}, 'players': []}
    if forecast['simulation'].get('status') == 'ready':
        for p, n in [('q1', 1), ('h1', 2), ('full', 4)]:
            if p != 'full' and not has_quarters(actual):
                continue
            a = actual['awayPoints'] if p == 'full' else sum(actual['awayLineScores'][:n])
            h = actual['homePoints'] if p == 'full' else sum(actual['homeLineScores'][:n])
            model = forecast['simulation']['periods'][p]
            out['periods'][p] = {'awayActual': a, 'homeActual': h,
                                 'awayError': round(model['away']['mean']-a, 2),
                                 'homeError': round(model['home']['mean']-h, 2),
                                 'totalError': round(model['total']['mean']-a-h, 2),
                                 'totalIn80Range': model['total']['p10'] <= a+h <= model['total']['p90'],
                                 'winnerCorrect': ((a > h) == (model['awayWin'] > model['homeWin'])) if a != h else None,
                                 'brier': round((model['awayWin']-int(a > h))**2, 5)}
    covered_teams = {t for gid, t, pid in player_records if gid == str(actual['id'])}
    for player in forecast.get('players', []):
        if player['team'] not in covered_teams:
            continue
        observed = player_records.get((str(actual['id']), player['team'], player['id']), {}).get('stats', {})
        for field, pred in player['stats'].items():
            value = observed.get(field, 0)
            out['players'].append({'id': player['id'], 'name': player['name'], 'stat': field,
                                    'projected': pred['mean'], 'actual': value,
                                    'error': round(pred['mean']-value, 2)})
    return out


def metrics(grades):
    output = {}
    for period in ('q1', 'h1', 'full'):
        rows = [g['periods'][period] for g in grades if period in g['periods']]
        if not rows:
            output[period] = {'games': 0}
            continue
        scored = [r for r in rows if r['winnerCorrect'] is not None]
        output[period] = {'games': len(rows), 'scoreMAE': round(float(np.mean([abs(r[f]) for r in rows for f in ('awayError','homeError')])),2),
                          'totalMAE': round(float(np.mean([abs(r['totalError']) for r in rows])),2),
                          'winnerAccuracy': round(float(np.mean([r['winnerCorrect'] for r in scored])),4) if scored else None,
                          'brier': round(float(np.mean([r['brier'] for r in rows])),4),
                          'rangeCoverage': round(float(np.mean([r['totalIn80Range'] for r in rows])),4)}
    grouped = defaultdict(list)
    for g in grades:
        for p in g['players']:
            grouped[p['stat']].append(abs(p['error']))
    output['players'] = {k: {'forecasts': len(v), 'MAE': round(float(np.mean(v)),2)} for k,v in grouped.items()}
    return output


def build(now, data_dir, fetch_players=False):
    games = load(data_dir / 'games-2026.json', [])
    if not games:
        raise ValueError('No schedule/game data')
    if fetch_players:
        records, issues = refresh_boxes(games, now, data_dir)
    else:
        boxes = []
        for p in (data_dir / 'player-boxes').glob('*.json'):
            boxes.extend(load(p, {}).get('games', []))
        records = parse_players(boxes)
        issues = [] if records else ['Player box scores have not been fetched yet.']
    sim_dir = data_dir / 'simulator'
    receipt_dir = sim_dir / 'receipts'
    receipt_dir.mkdir(parents=True, exist_ok=True)
    # Only box scores belonging to completed games available before this run enter forecasts.
    past_ids = {str(g['id']) for g in games if completed(g, now)}
    pre_records = {k: v for k,v in records.items() if k[0] in past_ids}
    eligible = [g for g in games if not g.get('completed') and not g.get('startTimeTBD')
                and now < date(g['startDate']) <= now + timedelta(days=7)
                and (g.get('homeClassification') == 'fbs' or g.get('awayClassification') == 'fbs')]
    for g in eligible:
        path = receipt_dir / f"{g['id']}.json"
        previous = load(path, {})
        if previous and (previous.get('grade') or date(previous['latest']['kickoff']) <= now):
            continue
        histories = [x for x in games if completed(x, now) and has_quarters(x)]
        fingerprint = digest([VERSION, g, histories, sorted((list(k),v) for k,v in pre_records.items())])
        if previous.get('latest', {}).get('inputHash') == fingerprint:
            continue
        forecast = {'gameId': g['id'], 'away': g['awayTeam'], 'home': g['homeTeam'],
                    'kickoff': g['startDate'], 'neutralSite': g.get('neutralSite', False),
                    'generatedAt': stamp(now), 'modelVersion': VERSION, 'inputHash': fingerprint,
                    'sourceThrough': max((x['startDate'] for x in histories), default=None),
                    'simulation': simulate_game(g, games, now),
                    'players': simulate_players(g, games, pre_records, now),
                    'playerMethod': 'Separate recency-weighted empirical workload baseline; not opponent-adjusted or lineup-confirmed.'}
        receipt = {'first': previous.get('first', forecast), 'latest': forecast,
                   'revisions': previous.get('revisions', 0) + 1}
        save(path, receipt)
    by_id = {g['id']: g for g in games}
    forecasts, grades = [], []
    for path in sorted(receipt_dir.glob('*.json')):
        receipt = load(path, {})
        f = receipt['latest']
        actual = by_id.get(f['gameId'])
        if actual and completed(actual, now):
            receipt['grade'] = grade(f, actual, records)
            save(path, receipt)
        if receipt.get('grade'):
            grades.append(receipt['grade'])
        forecasts.append({**f, 'revisions': receipt['revisions'], 'firstSavedAt': receipt['first']['generatedAt'],
                          'grade': receipt.get('grade')})
    latest = {'generatedAt': stamp(now), 'modelVersion': VERSION, 'runs': RUNS,
              'method': 'Empirical paired-quarter Monte Carlo baseline. Quarter means use ridge offense/opponent-defense ratings and a venue term, shrunk by four observations. Approximate score model; not a play-level simulator.',
              'limitations': ['Uncalibrated probabilities until enough future forecasts are graded.',
                              'No confirmed injuries, depth chart or weather adjustment.',
                              'Player estimates resample up to five covered team games; missing players count as zero only in covered boxes.',
                              'Player distributions are separate historical baselines, not reconciled to simulated team totals.'],
              'source': 'CollegeFootballData game scores and player box scores', 'issues': issues,
              'forecasts': sorted(forecasts, key=lambda f: f['kickoff']), 'metrics': metrics(grades)}
    save(sim_dir / 'latest.json', latest)
    print(f"Built {len(forecasts)} saved forecasts; {len(grades)} honestly graded games; {len(pre_records)} player-game records")
    for issue in issues:
        print(issue)
    return latest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', help='UTC ISO timestamp; no retrospective accuracy claims')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--fetch-players', action='store_true')
    args = parser.parse_args()
    build(date(args.as_of) if args.as_of else datetime.now(timezone.utc), args.data_dir, args.fetch_players)
