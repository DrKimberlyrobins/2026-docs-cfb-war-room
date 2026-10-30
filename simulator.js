/* Saved server-generated forecasts. This UI never manufactures a forecast. */
(() => {
  'use strict';
  const root = document.getElementById('simulator');
  const $ = id => document.getElementById(id);
  const el = (tag, text, parent, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    if (parent) parent.append(n);
    return n;
  };
  const pct = n => (100*n).toFixed(1)+'%';
  const fmt = n => Number.isFinite(n) ? n.toFixed(1) : '—';
  const ct = value => new Date(value).toLocaleString('en-US', {timeZone:'America/Chicago',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' CT';
  const day = value => new Intl.DateTimeFormat('en-CA', {timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  let data, selected;
  root.innerHTML = '<div class="sim-eyebrow">DOC’S SIMULATION LAB</div><h2>10,000 games. One saved forecast.</h2><p id="simStatus" role="status">Loading saved simulations…</p><div class="sim-controls"><label>Game date (Central)<input type="date" id="simDate"></label><label>Scheduled matchup<select id="simGame"><option>Loading…</option></select></label></div><div id="simBody"></div><details><summary>Method, data, and accuracy record</summary><div id="simMethod"></div></details>';

  function table(parent, headings, rows) {
    const wrap = el('div', undefined, parent, 'sim-scroll');
    const t = el('table', undefined, wrap);
    const tr = el('tr', undefined, el('thead', undefined, t));
    headings.forEach(h => el('th', h, tr));
    const body = el('tbody', undefined, t);
    rows.forEach(row => { const r = el('tr', undefined, body); row.forEach(v => el('td', String(v), r)); });
    return t;
  }

  function probability(hist, line, mode) {
    let win = 0, push = 0, count = 0;
    for (const [v,n] of hist) {
      const result = mode === 'spread' ? v + line : v - line;
      count += n; if (result > 0) win += n; else if (result === 0) push += n;
    }
    return {win: win/count, push: push/count, lose: (count-win-push)/count};
  }

  function refreshGames() {
    const list = data.forecasts.filter(f => day(f.kickoff) === $('simDate').value);
    $('simGame').replaceChildren();
    for (const f of list) {
      const option = el('option', `${f.away} @ ${f.home} · ${ct(f.kickoff)}${f.grade ? ' · GRADED' : ''}`, $('simGame'));
      option.value = String(f.gameId);
    }
    if (!list.length) el('option', 'No saved forecasts for this date', $('simGame'));
    show();
  }

  function show() {
    selected = data.forecasts.find(f => String(f.gameId) === $('simGame').value);
    const body = $('simBody'); body.replaceChildren();
    if (!selected) {
      el('p', 'Choose another date. Forecasts are created for scheduled FBS matchups up to seven days ahead. Past games appear only when a forecast was saved before kickoff.', body);
      return;
    }
    const f = selected;
    el('h3', `${f.away} at ${f.home}`, body);
    const openMatchup=el('button','Open this matchup in the War Room below',body);openMatchup.type='button';
    openMatchup.addEventListener('click',()=>{
      const away=$('awayTeam'),home=$('homeTeam');
      if(!Array.from(away.options).some(o=>o.value===f.away)||!Array.from(home.options).some(o=>o.value===f.home))return;
      away.value=f.away;home.value=f.home;home.dispatchEvent(new Event('change',{bubbles:true}));
    });
    el('p', `Saved ${ct(f.generatedAt)} · First receipt ${ct(f.firstSavedAt)} · ${f.modelVersion}`, body, 'sim-muted');
    el('p', `${new Date(f.kickoff) > new Date() ? 'PREGAME' : f.grade ? 'FINAL — GRADED' : 'LOCKED AT KICKOFF — AWAITING FINAL'} · ${f.neutralSite ? 'Neutral site' : 'Home/away adjusted'} · Input ${f.inputHash.slice(0,12)}`, body, 'sim-badge');
    if (f.simulation.status !== 'ready') {
      el('p', `Insufficient observed quarter history: ${f.simulation.awayGames} away-team games; ${f.simulation.homeGames} home-team games.`, body);
      return;
    }
    el('p', `${f.simulation.runs.toLocaleString()} simulations · Team samples ${f.simulation.awayGames} / ${f.simulation.homeGames} · ${f.simulation.leagueGames} league games · Probabilities are uncalibrated estimates.`, body, 'sim-muted');
    table(body, ['Period',f.away,f.home,'Total','Total 10th–90th percentile','Away / Home win','Tie'],
      [['q1','1Q'],['h1','1H'],['full','Full + OT']].map(([key,label]) => {
        const p = f.simulation.periods[key];
        return [label,fmt(p.away.mean),fmt(p.home.mean),fmt(p.total.mean),`${p.total.p10}–${p.total.p90}`,`${pct(p.awayWin)} / ${pct(p.homeWin)}`,pct(p.tie)];
      }));
    el('p', 'Percentile ranges describe simulated outcomes; future coverage has not yet been established. Quarter and half wins exclude ties.', body, 'sim-muted');

    el('h3', 'Compare a market line', body);
    const controls = el('div', undefined, body, 'sim-controls');
    const pl = el('label', 'Period', controls); const period = el('select', undefined, pl);
    for (const [value,label] of [['full','Full + OT'],['h1','First half'],['q1','First quarter']]) { const o=el('option',label,period);o.value=value; }
    const sl = el('label', `Away spread (${f.away})`, controls); const spread = el('input',undefined,sl); spread.type='number';spread.step='0.5';spread.placeholder='Example: -8.5';
    const tl = el('label', 'Game total', controls); const total = el('input',undefined,tl);total.type='number';total.step='0.5';total.placeholder='Example: 47.5';
    const output = el('p', 'Enter a line to calculate its simulated probability.', body); output.setAttribute('aria-live','polite');
    const calculate = () => {
      const p=f.simulation.periods[period.value], parts=[];
      if (spread.value !== '' && Number.isFinite(spread.valueAsNumber)) {const r=probability(p.marginHist,spread.valueAsNumber,'spread');parts.push(`${f.away} ${spread.valueAsNumber>=0?'+':''}${spread.valueAsNumber}: cover ${pct(r.win)}, push ${pct(r.push)}, opposite ${pct(r.lose)}`);}
      if (total.value !== '' && Number.isFinite(total.valueAsNumber)) {const r=probability(p.totalHist,total.valueAsNumber,'total');parts.push(`Total ${total.value}: over ${pct(r.win)}, under ${pct(r.lose)}, push ${pct(r.push)}`);}
      output.textContent=parts.join(' · ') || 'Enter a line to calculate its simulated probability.';
    };
    [period,spread,total].forEach(n=>n.addEventListener('input',calculate));
    // Use only finite, already-loaded Kambi values matching the selected teams.
    const sync = el('button','Use current War Room market lines',body);sync.type='button';
    sync.addEventListener('click',()=>{
      if ($('awayTeam').value !== f.away || $('homeTeam').value !== f.home) {output.textContent='Select this same matchup in the War Room before importing its lines.';return;}
      const lines=typeof marketBoardLines === 'undefined' ? null : marketBoardLines;
      const s=period.value==='full'?lines?.spread.awayLine:lines?.[period.value==='h1'?'firstHalf':'firstQuarter'].spreadAway;
      const t=period.value==='full'?lines?.gameTotal.line:lines?.[period.value==='h1'?'firstHalf':'firstQuarter'].total;
      spread.value=Number.isFinite(s)?s:'';total.value=Number.isFinite(t)?t:'';calculate();
      if (spread.value==='' && total.value==='') output.textContent='No verified lines are loaded for this period. You can enter the line manually.';
    });

    el('h3','Player workload baselines',body);
    el('p',f.playerMethod+' Availability and starting status are unverified. The range cannot include an unseen role change.',body,'sim-muted');
    if (!f.players.length) el('p','Player box scores are not connected for this forecast. No player numbers have been filled in.',body);
    else {
      const label=el('label','Search player',body);const search=el('input',undefined,label);search.type='search';search.placeholder='Type a player name';
      const list=el('div',undefined,body);
      const renderPlayers=()=>{
        list.replaceChildren();
        for(const team of [f.away,f.home]) {
          el('h4',team,list);
          const players=f.players.filter(p=>p.team===team && p.name.toLowerCase().includes(search.value.toLowerCase()));
          table(list,['Player','Sample','Pass C/A · Yds','Rush Att · Yds','Rec · Yds','TD pass / rush / rec'],players.map(p=>{
            const v=k=>fmt(p.stats[k]?.mean);
            return [p.name+(p.inLatestBox?'':' · absent latest box'),p.sampleGames,`${v('completions')}/${v('passAttempts')} · ${v('passYards')}`,`${v('rushAttempts')} · ${v('rushYards')}`,`${v('receptions')} · ${v('recYards')}`,`${v('passTD')} / ${v('rushTD')} / ${v('recTD')}`];
          }));
        }
      }; search.addEventListener('input',renderPlayers);renderPlayers();
      const tools=el('details',undefined,body);el('summary','Inspect player range and prop line',tools);
      const ps=el('select',undefined,tools);ps.setAttribute('aria-label','Player');
      f.players.forEach((p,i)=>{const o=el('option',`${p.name} · ${p.team}`,ps);o.value=i;});
      const stat=el('select',undefined,tools);stat.setAttribute('aria-label','Player statistic');
      const line=el('input',undefined,tools);line.type='number';line.step='.5';line.placeholder='Prop line';line.setAttribute('aria-label','Player prop line');
      const info=el('p',undefined,tools);info.setAttribute('aria-live','polite');
      const fill=()=>{stat.replaceChildren();Object.keys(f.players[+ps.value].stats).forEach(k=>{const o=el('option',k,stat);o.value=k;});inspect();};
      const inspect=()=>{const p=f.players[+ps.value],s=p.stats[stat.value];if(!s)return;info.textContent=`${p.name}: mean ${fmt(s.mean)}, median ${fmt(s.median)}, 10th–90th percentile ${s.p10}–${s.p90}. Last box ${ct(p.lastSeen)}. `;if(line.value!==''&&Number.isFinite(line.valueAsNumber)){const r=probability(s.hist,line.valueAsNumber,'total');info.textContent+=`Above ${pct(r.win)} · Below ${pct(r.lose)} · Push ${pct(r.push)}. Historical resampling estimate; uncalibrated.`;}};
      ps.addEventListener('change',fill);stat.addEventListener('change',inspect);line.addEventListener('input',inspect);fill();
    }
    if(f.grade){
      el('h3','Saved pregame forecast vs final',body);
      table(body,['Period','Actual away / home','Away error','Home error','Total error'],Object.entries(f.grade.periods).map(([p,r])=>[p,`${r.awayActual} / ${r.homeActual}`,r.awayError,r.homeError,r.totalError]));
      el('p','Error = projected − actual. Accuracy measures distance in either direction.',body,'sim-muted');
    }
    const receipt=el('a','View preserved first and latest pregame receipts',body);receipt.href=`data/simulator/receipts/${f.gameId}.json`;receipt.target='_blank';receipt.rel='noopener';
  }

  fetch('data/simulator/latest.json', {cache:'no-store'}).then(r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json();}).then(result=>{
    data=result;
    $('simStatus').textContent=`Updated ${ct(data.generatedAt)} · ${data.forecasts.length} saved matchups · All times Central`;
    const method=$('simMethod');el('p',data.method,method);el('p',`Source: ${data.source}`,method);
    data.limitations.forEach(t=>el('p',t,method));data.issues.forEach(t=>el('p',t,method));
    const m=data.metrics;
    table(method,['Period','Graded games','Team score MAE','Total MAE','Winner accuracy','80% range coverage'],['q1','h1','full'].map(p=>{const r=m[p];return [p,r.games,r.games?r.scoreMAE:'Not established',r.games?r.totalMAE:'—',r.games&&r.winnerAccuracy!==null?pct(r.winnerAccuracy):'—',r.games?pct(r.rangeCoverage):'—'];}));
    if(Object.keys(m.players).length)table(method,['Player statistic','Graded forecasts','MAE'],Object.entries(m.players).map(([k,v])=>[k,v.forecasts,v.MAE]));
    el('p','MAE = mean absolute error; smaller is better. Only forecasts saved before kickoff are graded. No historical reconstruction is counted as a live record.',method);
    const today=day(new Date());const dates=[...new Set(data.forecasts.map(f=>day(f.kickoff)))].sort();
    $('simDate').value=dates.includes(today)?today:dates.find(d=>d>=today)||dates.at(-1)||today;
    $('simDate').addEventListener('change',refreshGames);$('simGame').addEventListener('change',show);refreshGames();
  }).catch(err=>{$('simStatus').textContent=`Saved simulations could not be loaded (${err.message}). Check the CFB Simulator GitHub Action.`;});
  for(const id of ['awayTeam','homeTeam']) $(id).addEventListener('change',()=>{
    if(!data)return;
    const f=data.forecasts.find(f=>f.away===$('awayTeam').value&&f.home===$('homeTeam').value);
    if(!f)return;
    $('simDate').value=day(f.kickoff);refreshGames();$('simGame').value=String(f.gameId);show();
  });
})();
