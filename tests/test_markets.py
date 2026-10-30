import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('markets',Path(__file__).resolve().parents[1]/'scripts/markets.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class MarketTests(unittest.TestCase):
    def simulation(self):
        return {'status':'ready','periods':{'full':{
            'awayWin':.7,'homeWin':.3,'away':{'mean':30},'home':{'mean':20},'total':{'mean':50},
            'marginHist':[[10,7],[-3,3]],'totalHist':[[50,7],[43,3]]}}}

    def test_away_favorite_spread_sign(self):
        line=m.normalize_line({'provider':'Test','spread':8.5,'overUnder':47.5},'2026-10-30T20:00:00Z')
        d=m.directions(self.simulation(),'Away','Home',line)['full']
        self.assertEqual(d['spread']['team'],'Away')
        self.assertEqual(d['spread']['line'],-8.5)
        self.assertEqual(d['spread']['probability'],.7)
        self.assertEqual(d['total']['side'],'over')

    def test_home_favorite_and_under(self):
        line=m.normalize_line({'spread':-5.5,'overUnder':55},'now')
        d=m.directions(self.simulation(),'Away','Home',line)['full']
        self.assertEqual(d['spread']['side'],'away')
        self.assertEqual(d['spread']['line'],5.5)
        self.assertEqual(d['spread']['probability'],1)
        self.assertEqual(d['total']['side'],'under')

    def test_push_and_opposite_side(self):
        line=m.normalize_line({'spread':10,'overUnder':50},'now')
        d=m.directions(self.simulation(),'Away','Home',line)['full']
        self.assertEqual(d['spread']['side'],'home')
        self.assertEqual(d['spread']['line'],10)
        self.assertEqual(d['spread']['pushProbability'],.7)
        self.assertEqual(d['total']['side'],'under')
        f={'directions':{'full':d}}
        self.assertEqual(m.grade_directions(f,{'awayPoints':30,'homePoints':20}),{'winner':'win','spread':'push','total':'push'})

    def test_absent_market_has_projection_but_no_invented_direction(self):
        d=m.directions(self.simulation(),'Away','Home',None)['full']
        self.assertEqual(d['winner']['team'],'Away')
        self.assertEqual(d['projectedTotal'],50)
        self.assertNotIn('spread',d)
        self.assertNotIn('total',d)

    def test_consensus_uses_one_provider(self):
        lines=[m.normalize_line({'provider':'Other','spread':5,'overUnder':40},'now'),
               m.normalize_line({'provider':'consensus','spread':6,'overUnder':41},'now')]
        self.assertEqual(m.choose_market(lines)['provider'],'consensus')
        self.assertIsNone(m.numeric(None));self.assertIsNone(m.numeric(''));self.assertEqual(m.numeric(0),0)


if __name__=='__main__':unittest.main()
