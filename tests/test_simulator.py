import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('sim', Path(__file__).resolve().parents[1] / 'scripts/simulate.py')
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,30,20,tzinfo=timezone.utc)
        self.games = []
        for i in range(16):
            self.games.append({'id': i, 'week': i//2+1, 'startDate':sim.stamp(self.now-timedelta(days=2+i)),
                               'awayTeam':'A' if i%2 else 'B','homeTeam':'B' if i%2 else 'A',
                               'awayClassification':'fbs','homeClassification':'fbs','completed':True,
                               'awayLineScores':[7,3,7,0], 'homeLineScores':[0,7,7,7],
                               'awayPoints':17,'homePoints':21})
        self.game = {'id':100,'week':9,'startDate':sim.stamp(self.now+timedelta(hours=2)),
                     'awayTeam':'A','homeTeam':'B','awayClassification':'fbs','homeClassification':'fbs','completed':False}

    def test_future_results_cannot_change_simulation(self):
        baseline=sim.simulate_game(self.game,self.games,self.now,1000)
        future=copy.deepcopy(self.games[0]);future.update(id=999,startDate=sim.stamp(self.now+timedelta(days=1)),awayPoints=1000,awayLineScores=[250]*4)
        self.assertEqual(baseline,sim.simulate_game(self.game,self.games+[future],self.now,1000))

    def test_counts_and_period_consistency(self):
        result=sim.simulate_game(self.game,self.games,self.now,10000)
        for p in result['periods'].values():
            self.assertAlmostEqual(p['awayWin']+p['homeWin']+p['tie'],1,places=4)
            for key in ('marginHist','totalHist','awayHist','homeHist'):
                self.assertEqual(sum(n for v,n in p[key]),10000)
            self.assertAlmostEqual(p['away']['mean']+p['home']['mean'],p['total']['mean'],delta=.02)
        for side in ('away','home','total'):
            means=[result['periods'][p][side]['mean'] for p in ('q1','h1','full')]
            self.assertEqual(sorted(means),means)

    def test_postkick_forecast_never_graded(self):
        forecast={'generatedAt':self.game['startDate']}
        self.assertIsNone(sim.grade(forecast,self.game,{}))

    def test_receipts_freeze_first_and_do_not_create_past_forecasts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp); sim.save(path/'games-2026.json',self.games+[self.game])
            first=sim.build(self.now,path)
            receipt=sim.load(path/'simulator/receipts/100.json',{})
            self.assertEqual(len(first['forecasts']),1)
            sim.build(self.now+timedelta(hours=1),path)
            self.assertEqual(sim.load(path/'simulator/receipts/100.json',{})['first'],receipt['first'])
            actual=copy.deepcopy(self.game); actual.update(completed=True,awayPoints=17,homePoints=21,awayLineScores=[7,3,7,0],homeLineScores=[0,7,7,7])
            sim.save(path/'games-2026.json',self.games+[actual])
            final=sim.build(self.now+timedelta(hours=6),path)
            self.assertEqual(final['metrics']['full']['games'],1)
            self.assertEqual(sim.load(path/'simulator/receipts/100.json',{})['latest'],receipt['latest'])

    def test_player_parser_and_missing_boxes(self):
        boxes=[{'id':1,'teams':[{'team':'A','categories':[{'name':'passing','types':[{'name':'C/ATT','athletes':[{'id':'p1','name':'QB','stat':'17/29'}]},{'name':'YDS','athletes':[{'id':'p1','name':'QB','stat':'225'}]}]}]}]}]
        records=sim.parse_players(boxes)
        self.assertEqual(records[('1','A','p1')]['stats'],{'completions':17,'passAttempts':29,'passYards':225})
        players=sim.simulate_players(self.game,self.games,records,self.now,100)
        self.assertEqual(len(players),1)
        self.assertEqual(players[0]['sampleGames'],1)
        self.assertEqual(players[0]['stats']['passYards']['mean'],225)
        boxes[0]['teams'][0]['categories'][0]['types'][0]['athletes'].append({'id':'0','name':'Team','stat':'0/0'})
        self.assertEqual(len(sim.parse_players(boxes)),1)

    def test_missing_score_not_a_zero(self):
        g=copy.deepcopy(self.games[0]);g['awayPoints']=None
        self.assertFalse(sim.completed(g,self.now))


if __name__=='__main__':
    unittest.main()
