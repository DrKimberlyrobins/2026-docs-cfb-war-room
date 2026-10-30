# DOC'S CFB Simulator

The Simulation Lab in `index.html` reads forecasts built by `scripts/simulate.py`.
It does not replace or silently relabel the original scoring engine below it.

The daily board lists every saved FBS matchup for the selected Central date.
Full-game winning side, spread direction and over/under are calculated automatically.
Market lines come from timestamped CFBD `/lines` snapshots; home spread is the
canonical convention (negative means home favored). One provider supplies both
spread and total, preferring a complete consensus snapshot when available.
Spread and total directions select the side occurring more often in simulations;
pushes are shown separately. An equal probability is shown as an even projection.
These directions are not advertised as validated profitable plays. A missing
market line is explicitly unavailable, while the model's spread and total remain
visible. 1Q and 1H model projections do not fabricate unconnected period markets.
Directions and captured lines are saved before kickoff and graded as win/loss/push.

## What runs

* 10,000 deterministic seeded draws for each scheduled FBS matchup in the next seven days.
* Completed CFBD quarter scores only. Ridge offense and opponent-defense quarter means,
  a venue term, and four-observation shrinkage. Historical quarter vectors are sampled
  together and scaled to these means. This is a baseline empirical score simulator,
  not a play-by-play engine. Integer rescaling can produce unusual football scores.
* 1Q, 1H, full-game-plus-overtime score means, percentiles and outcome histograms.
  Historical overtime pairs resolve regulation ties when available. Otherwise ties
  remain explicit. Win probabilities are uncalibrated model estimates.
* Separate player workload distributions from up to five covered team box scores,
  with recency weights. Missing box scores are excluded; absent players in covered
  boxes count as zero after their first observed game. A player must appear in one
  of the latest two covered boxes to be listed. These are not confirmed starters,
  injury-adjusted projections, opponent-adjusted props, or reconciled team totals.

## Receipts and grading

`data/simulator/receipts/<game-id>.json` preserves `first` permanently. `latest`
can update only before kickoff, when its input fingerprint changes. No forecast
is first created for a game already underway. Finals grade the latest saved
pregame forecast: score MAE, total MAE, winner accuracy, Brier score, simulated
80% total-range coverage, and player-stat MAE. Player grades require covered
postgame boxes. There is no backfilled live record or claimed historical hit rate.
Probabilities, simulation count and forecasting accuracy are separate concepts.

The initial first receipts may contain only team forecasts, before the first
authenticated player-box fetch. Subsequent pregame revisions may add players.
Missing injury/roster/weather feeds remain disclosed in the UI.

## Refresh

The existing CFBD_API_KEY repository secret is used only by GitHub Actions.
The simulator workflow runs on manual dispatch, relevant code pushes, the existing
daily data workflow's completion, and at minutes 17 and 47 hourly (UTC). GitHub
schedules can be delayed; forecasts show their actual generation time. No request
is made for a new credential. Player boxes are cached by week; recent boxes refresh.
API failures retain the prior cache and produce visible issues.

Run locally:

```sh
python -m pip install numpy==2.3.5
python -m unittest discover -s tests -v
python scripts/simulate.py
```

Set CFBD_API_KEY through the process environment and add `--fetch-players` to
fetch player data. Never put it in browser code or commit it. Files under
`data/player-boxes` contain public sports statistics only.

Source schema: https://api.collegefootballdata.com/api/games
