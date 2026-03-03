// Histogram layout constants (in SVG viewBox units)
const HISTOGRAM_VIEWBOX_WIDTH = 900, HISTOGRAM_VIEWBOX_HEIGHT = 300;
const HISTOGRAM_MARGIN = { top: 20, right: 24, bottom: 58, left: 68 };
const HISTOGRAM_WIDTH = HISTOGRAM_VIEWBOX_WIDTH - HISTOGRAM_MARGIN.left - HISTOGRAM_MARGIN.right;
const HISTOGRAM_HEIGHT = HISTOGRAM_VIEWBOX_HEIGHT - HISTOGRAM_MARGIN.top - HISTOGRAM_MARGIN.bottom;
const HISTOGRAM_BINS = 22;

// Line chart layout constants (in SVG viewBox units)
const CHART_VIEWBOX_WIDTH = 900, CHART_VIEWBOX_HEIGHT = 360;
const CHART_MARGIN = { top: 20, right: 160, bottom: 50, left: 72 };
const CHART_WIDTH = CHART_VIEWBOX_WIDTH - CHART_MARGIN.left - CHART_MARGIN.right;
const CHART_HEIGHT = CHART_VIEWBOX_HEIGHT - CHART_MARGIN.top - CHART_MARGIN.bottom;

// Display color for each asset category name (matches AssetCategory.display_name in Python).
const CATEGORY_COLORS = {
  'Cash':        '#58a6ff',
  '401K':        '#3fb950',
  'Roth 401K':   '#56d364',
  'IRA':         '#f0883e',
  'Roth IRA':    '#ffa657',
  'Stocks':      '#bc8cff',
  'Bonds':       '#79c0ff',
  '529 Plan':    '#ffa198',
  'HSA':         '#d2a8ff',
  'Real Estate': '#e3b341',
};

// Global mutable state.
let appData          = null;   // Full /data response
let selectedBin      = -1;     // Active histogram bar index
let lockedYear       = null;   // Locked year in the detail chart, or null
let isRunning        = false;  // True while a /simulate request is in flight
let runDebounceTimer = null;   // Pending debounce timer ID

/**
 * Format a dollar amount as a compact string, e.g. $1.23M, $456K, $789.
 *
 * @param {number} amount
 * @returns {string}
 */
function formatMoney(amount) {
  const sign = amount < 0 ? '-' : '';
  const absAmount = Math.abs(amount);
  const formatted = absAmount >= 1e6 ? parseFloat((absAmount / 1e6).toFixed(2)) + 'M'
                  : absAmount >= 1e3 ? (absAmount / 1e3).toFixed(0) + 'K'
                  : absAmount.toFixed(0);
  return sign + '$' + formatted;
}

/**
 * Compute a "nice" y-axis ceiling and grid step for a given data maximum.
 * Adds 2% headroom, then rounds up to the smallest step from the set
 * {1, 2, 2.5, 5} × 10^n that produces ≤5 grid lines.
 *
 * @param {number} dataMax
 * @returns {{yMax: number, step: number, steps: number}}
 */
function niceAxis(dataMax) {
  if (!dataMax) return { yMax: 1, step: 0.25, steps: 4 };
  const rawMax = dataMax * 1.02;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawMax)));
  for (const multiple of [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10]) {
    const step = multiple * magnitude;
    const yMax = Math.ceil(rawMax / step) * step;
    const steps = Math.round(yMax / step);
    if (steps <= 5) {
      return { yMax, step, steps };
    }
  }
  return { yMax: rawMax, step: rawMax / 4, steps: 4 };
}

/**
 * Return an HSL color string for a histogram bar, interpolating hue from
 * red (0°) at ratio=0 to green (120°) at ratio=1.
 *
 * @param {number} ratio - Bin position in [0, 1].
 * @returns {string} CSS hsl() color string.
 */
function binColor(ratio) {
  const hue = ratio * 120;
  const saturation = 62;
  const lightness = 40 + ratio * 8;
  return `hsl(${hue.toFixed(1)},${saturation}%,${lightness.toFixed(1)}%)`;
}

/**
 * Create an SVG element with the given tag name and attributes.
 *
 * @param {string} tag - SVG tag name (e.g. 'rect', 'line').
 * @param {Object} attrs - Attribute name/value pairs to set on the element.
 * @returns {SVGElement}
 */
function svgTag(tag, attrs) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attrs)) {
    element.setAttribute(name, value);
  }
  return element;
}

/**
 * Create an SVG text element at the given position.
 *
 * @param {number} x
 * @param {number} y
 * @param {string} text - Text content.
 * @param {Object} attrs - Additional SVG attributes (e.g. text-anchor, fill).
 * @returns {SVGTextElement}
 */
function svgText(x, y, text, attrs = {}) {
  const tag = svgTag('text', { x, y, ...attrs });
  tag.textContent = text;
  return tag;
}

/**
 * Render the outcome distribution histogram into the #histogram SVG element.
 *
 * @param {number[]} totals - Final portfolio value from each simulation.
 * @param {number} startingTotal - Portfolio value at retirement start, drawn as a reference marker.
 * @param {number} median - Median final portfolio value (drawn as a reference marker).
 * @param {Array<{start_year: number, total: number}>} results - Result objects for drill-down.
 * @param {number} retirementLength - Number of years in the retirement period.
 */
function drawHistogram(totals, startingTotal, median, results, retirementLength) {
  const svg = document.getElementById('histogram');
  svg.innerHTML = '';

  const minVal = Math.min(...totals);
  const maxVal = Math.max(...totals);
  const span = maxVal - minVal || 1;
  const binWidth = span / HISTOGRAM_BINS;

  const counts = new Array(HISTOGRAM_BINS).fill(0);
  for (const total of totals) {
    counts[Math.min(Math.floor((total - minVal) / binWidth), HISTOGRAM_BINS - 1)]++;
  }
  const maxCount = Math.max(...counts);

  const binRuns = Array.from({ length: HISTOGRAM_BINS }, () => []);
  for (const result of results) {
    const idx = Math.min(Math.floor((result.total - minVal) / binWidth), HISTOGRAM_BINS - 1);
    binRuns[idx].push(result);
  }

  const xScale = value => HISTOGRAM_MARGIN.left + ((value - minVal) / span) * HISTOGRAM_WIDTH;
  const barWidth = HISTOGRAM_WIDTH / HISTOGRAM_BINS;

  // Y-axis grid + labels
  const Y_STEPS = 4;
  for (let i = 0; i <= Y_STEPS; i++) {
    const y = HISTOGRAM_MARGIN.top + (i / Y_STEPS) * HISTOGRAM_HEIGHT;
    const pct = ((Y_STEPS - i) / Y_STEPS * maxCount / totals.length * 100).toFixed(0);

    svg.appendChild(svgTag('line', {
      x1: HISTOGRAM_MARGIN.left, x2: HISTOGRAM_MARGIN.left + HISTOGRAM_WIDTH, y1: y, y2: y,
      stroke: '#30363d', 'stroke-width': '1',
    }));

    svg.appendChild(svgText(HISTOGRAM_MARGIN.left - 8, y + 4, pct + '%', {
      'text-anchor': 'end', fill: '#8b949e', 'font-size': '11',
    }));
  }

  // Histogram bars
  const tooltip = document.getElementById('tooltip');
  for (let i = 0; i < HISTOGRAM_BINS; i++) {
    if (counts[i] === 0) continue;
    const barHeight = (counts[i] / maxCount) * HISTOGRAM_HEIGHT;
    const barX = HISTOGRAM_MARGIN.left + i * barWidth;
    const barY = HISTOGRAM_MARGIN.top + HISTOGRAM_HEIGHT - barHeight;

    const rect = svgTag('rect', {
      x: barX + 1.5, width: barWidth - 3,
      y: barY, height: barHeight,
      fill: binColor(i / (HISTOGRAM_BINS - 1)),
      rx: '2',
    });

    rect.setAttribute('data-bin', i);

    const binMin = minVal + i * binWidth;
    const binMax = binMin + binWidth;
    const pct = (counts[i] / totals.length * 100).toFixed(1);

    rect.addEventListener('mouseenter', event => {
      tooltip.innerHTML =
        `<strong>${formatMoney(binMin)}&nbsp;&ndash;&nbsp;${formatMoney(binMax)}</strong><br>` +
        `${counts[i].toLocaleString()} simulation${counts[i] === 1 ? '' : 's'} &nbsp;(${pct}%)`;
      tooltip.classList.add('visible');
    });

    rect.addEventListener('mousemove', event => {
      tooltip.style.left = (event.clientX + 14) + 'px';
      tooltip.style.top  = (event.clientY - 10) + 'px';
    });

    rect.addEventListener('mouseleave', () => tooltip.classList.remove('visible'));

    rect.addEventListener('click', () => {
      const wasSelected = selectedBin === i;
      if (selectedBin >= 0) {
        const prev = svg.querySelector(`[data-bin="${selectedBin}"]`);
        if (prev) {
          prev.removeAttribute('stroke');
          prev.removeAttribute('stroke-width');
        }
      }
      if (wasSelected) {
        selectedBin = -1;
        document.getElementById('bin-detail').hidden = true;
      } else {
        selectedBin = i;
        rect.setAttribute('stroke', '#58a6ff');
        rect.setAttribute('stroke-width', '2');
        showBinDetail(binRuns[i], binMin, binMax, startingTotal, retirementLength);
      }
    });

    svg.appendChild(rect);
  }

  // Starting-total marker
  if (startingTotal >= minVal && startingTotal <= maxVal) {
    const markerX = xScale(startingTotal);
    svg.appendChild(svgTag('line', {
      x1: markerX, x2: markerX,
      y1: HISTOGRAM_MARGIN.top,
      y2: HISTOGRAM_MARGIN.top + HISTOGRAM_HEIGHT,
      stroke: '#8b949e', 'stroke-width': '1.5', 'stroke-dasharray': '4 4',
    }));
    svg.appendChild(svgText(markerX + 5, HISTOGRAM_MARGIN.top + 13, 'start', {
      fill: '#8b949e', 'font-size': '11',
    }));
  }

  // Median marker
  if (median >= minVal && median <= maxVal) {
    const markerX = xScale(median);
    svg.appendChild(svgTag('line', {
      x1: markerX, x2: markerX,
      y1: HISTOGRAM_MARGIN.top,
      y2: HISTOGRAM_MARGIN.top + HISTOGRAM_HEIGHT,
      stroke: '#58a6ff', 'stroke-width': '2', 'stroke-dasharray': '5 3',
    }));
    svg.appendChild(svgText(markerX + 5, HISTOGRAM_MARGIN.top + 28, 'median', {
      fill: '#58a6ff', 'font-size': '11',
    }));
  }

  // X-axis line
  svg.appendChild(svgTag('line', {
    x1: HISTOGRAM_MARGIN.left,
    x2: HISTOGRAM_MARGIN.left + HISTOGRAM_WIDTH,
    y1: HISTOGRAM_MARGIN.top + HISTOGRAM_HEIGHT,
    y2: HISTOGRAM_MARGIN.top + HISTOGRAM_HEIGHT,
    stroke: '#30363d', 'stroke-width': '1',
  }));

  // X-axis labels
  const X_LABELS = 5;
  for (let i = 0; i <= X_LABELS; i++) {
    const val = minVal + (i / X_LABELS) * span;
    const x = HISTOGRAM_MARGIN.left + (i / X_LABELS) * HISTOGRAM_WIDTH;
    const anchor = i === 0 ? 'start' : i === X_LABELS ? 'end' : 'middle';
    svg.appendChild(svgText(x, HISTOGRAM_MARGIN.top + HISTOGRAM_HEIGHT + 18, formatMoney(val), {
      'text-anchor': anchor, fill: '#8b949e', 'font-size': '11',
    }));
  }
}

/**
 * Populate and show the bin detail section with a summary card per simulation.
 *
 * @param {Array<{start_year: number, total: number}>} binRuns - Runs in this bin.
 * @param {number} binMin - Lower bound of the bin range.
 * @param {number} binMax - Upper bound of the bin range.
 * @param {number} startingTotal - Portfolio value at retirement start.
 * @param {number} retirementLength - Number of years in the retirement period.
 */
function showBinDetail(binRuns, binMin, binMax, startingTotal, retirementLength) {
  const section = document.getElementById('bin-detail');
  const title   = document.getElementById('bin-detail-title');
  const grid    = document.getElementById('bin-detail-grid');

  const count = binRuns.length;
  title.textContent =
    `${formatMoney(binMin)} \u2013 ${formatMoney(binMax)}`
    + `  \u00b7  ${count} simulation${count === 1 ? '' : 's'}`;

  grid.innerHTML = '';
  const sorted = [...binRuns].sort((a, b) => a.total - b.total);

  for (const run of sorted) {
    const endYear = run.start_year + retirementLength;
    const change = (run.total - startingTotal) / startingTotal * 100;

    const card = document.createElement('div');
    card.className = 'sim-card panel';

    const period = document.createElement('div');
    period.className = 'sim-card-period';
    period.textContent = `${run.start_year} \u2192 ${endYear}`;

    const total = document.createElement('div');
    total.className = 'sim-card-total';
    total.textContent = formatMoney(run.total);

    const changeEl = document.createElement('div');
    changeEl.className = 'sim-card-change ' + (change >= 0 ? 'positive' : 'negative');
    changeEl.textContent = (change >= 0 ? '+' : '') + change.toFixed(1) + '%';

    card.addEventListener('click', () => showDetailView(run));
    card.append(period, total, changeEl);
    grid.appendChild(card);
  }

  section.hidden = false;
  section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Switch to the detail view for a specific simulation result.
 *
 * @param {{start_year: number, total: number, history: Array}} result
 */
function showDetailView(result) {
  const { retirement, starting_total } = appData;
  const retirementLength = retirement.end_year - retirement.start_year;
  const historicalEndYear = result.start_year + retirementLength;
  const change = (result.total - starting_total) / starting_total * 100;
  const changeClass = change >= 0 ? 'positive' : 'negative';
  const changeValue = (change >= 0 ? '+' : '') + change.toFixed(1) + '%';

  document.getElementById('detail-nav-info').innerHTML =
    `<strong>${result.start_year}&nbsp;&rarr;&nbsp;${historicalEndYear}</strong>` +
    `&nbsp;&nbsp;&middot;&nbsp;&nbsp;${formatMoney(result.total)}` +
    `&nbsp;<span class="${changeClass}">(${changeValue})</span>`;

  document.getElementById('back-button').onclick = hideDetailView;

  document.getElementById('view-overview').hidden = true;
  document.getElementById('view-detail').hidden = false;
  window.scrollTo({ top: 0, behavior: 'instant' });

  drawLineChart(result.history, retirement.start_year, retirement.end_year, result.start_year);
  if (result.history.length > 0) {
    updateDetailTable(result.history[0], result.start_year, null);
  }
}

/**
 * Switch to the detail view showing the deterministic pre-retirement asset projection.
 */
function showPreRetirementView() {
  const { retirement, starting_total, pre_retirement_history } = appData;
  if (!pre_retirement_history.length) return;

  const firstYear = pre_retirement_history[0].year;

  document.getElementById('detail-nav-info').innerHTML =
    `Pre-retirement &nbsp;&middot;&nbsp;` +
    `<strong>${firstYear}&nbsp;&rarr;&nbsp;${retirement.start_year}</strong>` +
    `&nbsp;&nbsp;&middot;&nbsp;&nbsp;${formatMoney(starting_total)}`;

  document.getElementById('back-button').onclick = hideDetailView;

  document.getElementById('view-overview').hidden = true;
  document.getElementById('view-detail').hidden = false;
  window.scrollTo({ top: 0, behavior: 'instant' });

  drawLineChart(pre_retirement_history, firstYear, retirement.start_year, null);
  updateDetailTable(pre_retirement_history[0], null, null);
}

/**
 * Return to the overview, restoring the histogram selection state.
 */
function hideDetailView() {
  lockedYear = null;
  document.getElementById('view-detail').hidden = true;
  document.getElementById('view-overview').hidden = false;
}

/**
 * Render the asset performance line chart into the #line-chart SVG element.
 *
 * @param {Array<{year: number, assets: Object}>} history - Per-year asset snapshots.
 * @param {number} startYear - First year of the retirement period.
 * @param {number} endYear - Last year of the retirement period (inclusive).
 * @param {number} historicalStartYear - First year of the historical S&P 500 period used.
 */
function drawLineChart(history, startYear, endYear, historicalStartYear) {
  const svg = document.getElementById('line-chart');
  svg.innerHTML = '';

  lockedYear = null;

  if (!history.length) return;

  const retirementLength = endYear - startYear || 1;

  const uniqueCategories = new Set();
  for (const snapshot of history) {
    for (const category of Object.keys(snapshot.assets)) {
      uniqueCategories.add(category);
    }
  }

  // Collect all categories present in any snapshot, sorted by first-year value descending.
  const firstAssets = history[0].assets;
  const categories = [...uniqueCategories]
    .sort((a, b) => (firstAssets[b] || 0) - (firstAssets[a] || 0));

  // Max y: find the largest single-year value, then snap to a nice axis ceiling.
  let rawYMax = 0;
  for (const snapshot of history) {
    for (const category of Object.keys(snapshot.assets)) {
      const value = snapshot.assets[category];
      if (value > rawYMax) {
        rawYMax = value;
      }
    }
  }
  const { yMax, steps: Y_STEPS } = niceAxis(rawYMax);

  const xScale = year  => CHART_MARGIN.left + (year - startYear) / retirementLength * CHART_WIDTH;
  const yScale =
    value => CHART_MARGIN.top + CHART_HEIGHT - Math.max(0, value) / yMax * CHART_HEIGHT;

  // Create a map of snapshots by year.
  const snapshots = new Map();
  for (const snapshot of history) {
    snapshots.set(snapshot.year, snapshot);
  }

  // Y-axis grid + labels
  for (let i = 0; i <= Y_STEPS; i++) {
    const value = (Y_STEPS - i) / Y_STEPS * yMax;
    const y = yScale(value);
    svg.appendChild(svgTag('line', {
      x1: CHART_MARGIN.left, x2: CHART_MARGIN.left + CHART_WIDTH, y1: y, y2: y,
      stroke: '#30363d', 'stroke-width': '1',
    }));
    svg.appendChild(svgText(CHART_MARGIN.left - 8, y + 4, formatMoney(value), {
      'text-anchor': 'end', fill: '#8b949e', 'font-size': '11',
    }));
  }

  // X-axis line + labels
  svg.appendChild(svgTag('line', {
    x1: CHART_MARGIN.left, x2: CHART_MARGIN.left + CHART_WIDTH,
    y1: CHART_MARGIN.top + CHART_HEIGHT, y2: CHART_MARGIN.top + CHART_HEIGHT,
    stroke: '#30363d', 'stroke-width': '1',
  }));

  // Use an integer step to avoid floating-point rounding placing labels on fractional years.
  // Math.round gives step=1 for periods up to ~8 years, step=2 for ~9–14 years, etc.
  const xLabels = [];
  const labelStep = Math.max(1, Math.round(retirementLength / 6));
  for (let year = startYear; year < endYear; year += labelStep) {
    xLabels.push(year);
  }
  xLabels.push(endYear);

  for (let i = 0; i < xLabels.length; i++) {
    const x = xScale(xLabels[i]);
    const anchor = i === 0 ? 'start' : i === xLabels.length - 1 ? 'end' : 'middle';
    svg.appendChild(svgText(x, CHART_MARGIN.top + CHART_HEIGHT + 18, String(xLabels[i]), {
      'text-anchor': anchor, fill: '#8b949e', 'font-size': '11',
    }));
  }

  // Data lines (one path per category, with gap support)
  for (const category of categories) {
    let path = '';
    let prevPresent = false;
    for (const snapshot of history) {
      const value = snapshot.assets[category];
      if (value > 0) {
        const x = xScale(snapshot.year).toFixed(1);
        const y = yScale(value).toFixed(1);
        path += prevPresent ? `L${x} ${y} ` : `M${x} ${y} `;
        prevPresent = true;
      } else {
        if (prevPresent) {
          const x = xScale(snapshot.year).toFixed(1);
          path += `L${x} ${yScale(0).toFixed(1)} `;
        }
        prevPresent = false;
      }
    }
    if (path) {
      svg.appendChild(svgTag('path', {
        d: path.trim(), fill: 'none',
        stroke: CATEGORY_COLORS[category] || '#8b949e',
        'stroke-width': '2', 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      }));
    }
  }

  // Chart legend
  const legendX = CHART_MARGIN.left + CHART_WIDTH + 20;
  let legendY = CHART_MARGIN.top + 12;
  for (const category of categories) {
    const color = CATEGORY_COLORS[category] || '#8b949e';
    svg.appendChild(svgTag('rect', {
      x: legendX, y: legendY - 8, width: 12, height: 12, rx: '2', fill: color,
    }));
    svg.appendChild(svgText(legendX + 17, legendY + 1, category, {
      fill: '#e6edf3', 'font-size': '12',
    }));
    legendY += 22;
  }

  // Locked-year indicator: solid, stays visible until unlocked.
  const lockedLine = svgTag('line', {
    x1: 0, x2: 0,
    y1: CHART_MARGIN.top, y2: CHART_MARGIN.top + CHART_HEIGHT,
    stroke: '#58a6ff', 'stroke-width': '2',
    visibility: 'hidden',
  });
  svg.appendChild(lockedLine);

  // Hover cursor: dashed, follows the mouse and hides on leave.
  const cursorLine = svgTag('line', {
    x1: 0, x2: 0,
    y1: CHART_MARGIN.top, y2: CHART_MARGIN.top + CHART_HEIGHT,
    stroke: 'rgba(88,166,255,0.5)', 'stroke-width': '1.5', 'stroke-dasharray': '4 3',
    visibility: 'hidden',
  });
  svg.appendChild(cursorLine);

  // One hover dot per category.
  const hoverDots = {};
  for (const category of categories) {
    const dot = svgTag('circle', {
      r: '4', fill: CATEGORY_COLORS[category] || '#8b949e',
      stroke: '#0d1117', 'stroke-width': '1.5',
      visibility: 'hidden',
    });
    svg.appendChild(dot);
    hoverDots[category] = dot;
  }

  // Year label above cursor.
  const yearLabel = svgText(0, CHART_MARGIN.top - 6, '', {
    fill: '#58a6ff', 'font-size': '11', 'text-anchor': 'middle', visibility: 'hidden',
  });
  svg.appendChild(yearLabel);

  // Transparent overlay that captures all mouse events (appended last, on top).
  const overlay = svgTag('rect', {
    x: CHART_MARGIN.left, y: CHART_MARGIN.top,
    width: CHART_WIDTH, height: CHART_HEIGHT,
    fill: 'transparent', style: 'cursor: crosshair',
  });
  svg.appendChild(overlay);

  // Cursor helpers

  function setLockedLine(year) {
    if (year != null) {
      const x = xScale(year);
      lockedLine.setAttribute('x1', x);
      lockedLine.setAttribute('x2', x);
      lockedLine.setAttribute('visibility', 'visible');
    } else {
      lockedLine.setAttribute('visibility', 'hidden');
    }
  }

  function moveCursorTo(year) {
    const x = xScale(year);
    cursorLine.setAttribute('x1', x);
    cursorLine.setAttribute('x2', x);
    cursorLine.setAttribute('visibility', 'visible');
    yearLabel.setAttribute('x', x);
    yearLabel.textContent = year;
    yearLabel.setAttribute('visibility', 'visible');

    const snapshot = snapshots.get(year);
    for (const category of categories) {
      const dot = hoverDots[category];
      const value = snapshot && snapshot.assets[category];
      if (value > 0) {
        dot.setAttribute('cx', x);
        dot.setAttribute('cy', yScale(value));
        dot.setAttribute('visibility', 'visible');
      } else {
        dot.setAttribute('visibility', 'hidden');
      }
    }
  }

  function hideCursor() {
    cursorLine.setAttribute('visibility', 'hidden');
    yearLabel.setAttribute('visibility', 'hidden');
    for (const dot of Object.values(hoverDots)) {
      dot.setAttribute('visibility', 'hidden');
    }
  }

  function yearFromEvent(event) {
    const rect = svg.getBoundingClientRect();
    const svgX = (event.clientX - rect.left) / rect.width * CHART_VIEWBOX_WIDTH;
    const year = startYear + (svgX - CHART_MARGIN.left) / CHART_WIDTH * retirementLength;
    return Math.round(Math.max(startYear, Math.min(year, endYear)));
  }

  // Mouse events

  const historicalYear = historicalStartYear != null
    ? year => historicalStartYear + (year - startYear)
    : () => null;

  overlay.addEventListener('mousemove', event => {
    const year = yearFromEvent(event);
    moveCursorTo(year);
    updateDetailTable(snapshots.get(year), historicalYear(year), snapshots.get(year - 1));
  });

  overlay.addEventListener('mouseleave', () => {
    hideCursor();
    if (lockedYear != null) {
      updateDetailTable(
        snapshots.get(lockedYear), historicalYear(lockedYear), snapshots.get(lockedYear - 1));
    } else {
      updateDetailTable(snapshots.get(startYear), historicalYear(startYear), null);
    }
  });

  overlay.addEventListener('click', event => {
    const year = yearFromEvent(event);
    if (lockedYear === year) {
      lockedYear = null;
      setLockedLine(null);
    } else {
      lockedYear = year;
      setLockedLine(year);
    }
    moveCursorTo(year);
    updateDetailTable(snapshots.get(year), historicalYear(year), snapshots.get(year - 1));
  });
}

/**
 * Return a <td> HTML string for a year-over-year percentage change.
 * Shows '—' when there is no previous value to compare against.
 *
 * @param {number} value - Current value.
 * @param {number} prevValue - Previous year's value (0 or undefined means no comparison).
 * @returns {string} HTML for a <td class="num ..."> cell.
 */
function yearOverYearComparisonCell(value, prevValue) {
  if (!prevValue) return '<td class="num">\u2014</td>';
  const pct = (value - prevValue) / prevValue * 100;
  const cls = pct >= 0 ? 'positive' : 'negative';
  return `<td class="num ${cls}">${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%</td>`;
}

/**
 * Render a detail table's body and footer from a raw data object.
 * Used by both the assets and budget tables.
 *
 * @param {HTMLElement} tbody - The <tbody> to populate.
 * @param {HTMLElement} tfoot - The <tfoot> to populate.
 * @param {Object} data - Raw name→value object; zero/missing values are filtered out.
 * @param {Object|null} prevData - Previous year's data for YoY comparison, or null.
 * @param {function(HTMLElement, string): void} renderName - Fills the name <td> for each row.
 */
function renderDetailTable(tbody, tfoot, data, prevData, renderName) {
  const entries = Object.entries(data)
    .filter(([, value]) => value > 0)
    .sort(([, a], [, b]) => b - a);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const prevTotal = prevData
    ? Object.values(prevData)
        .filter(value => value > 0)
        .reduce((sum, value) => sum + value, 0)
    : 0;

  tbody.innerHTML = '';
  for (const [name, value] of entries) {
    const share = total > 0 ? (value / total * 100).toFixed(1) + '%' : '-';
    const row = document.createElement('tr');
    const nameCell = document.createElement('td');
    renderName(nameCell, name);
    row.appendChild(nameCell);
    row.insertAdjacentHTML('beforeend',
      yearOverYearComparisonCell(value, prevData?.[name]) +
      `<td class="num">${share}</td>` +
      `<td class="num">${formatMoney(value)}</td>`);
    tbody.appendChild(row);
  }

  const footNameCell = document.createElement('td');
  renderName(footNameCell, 'Total');
  const footRow = document.createElement('tr');
  footRow.appendChild(footNameCell);
  footRow.insertAdjacentHTML('beforeend',
    yearOverYearComparisonCell(total, prevTotal) +
    `<td class="num">100%</td>` +
    `<td class="num">${formatMoney(total)}</td>`);
  tfoot.innerHTML = '';
  tfoot.appendChild(footRow);
}

/**
 * Populate the assets and budget tables for a given year snapshot.
 *
 * @param {{year: number, assets: Object, budget: Object}|undefined} snapshot
 * @param {number|null} historicalYear - Corresponding historical S&P 500 year, or null.
 * @param {{assets: Object, budget: Object}|null|undefined} prevSnapshot - Previous year's snapshot for YoY.
 */
function updateDetailTable(snapshot, historicalYear, prevSnapshot) {
  const title = document.getElementById('detail-table-title');
  title.innerHTML = `${snapshot.year ?? '&mdash;'} `;
  if (historicalYear != null) {
    const basedOn = document.createElement('span');
    basedOn.className = 'detail-table-historical-year';
    basedOn.textContent = `(based on ${historicalYear})`;
    title.appendChild(basedOn);
  }

  const assetBody   = document.getElementById('detail-table-body');
  const assetFoot   = document.getElementById('detail-table-footer');
  const budgetBody  = document.getElementById('budget-table-body');
  const budgetFoot  = document.getElementById('budget-table-footer');

  if (!snapshot) {
    [assetBody, assetFoot, budgetBody, budgetFoot].forEach(el => el.innerHTML = '');
    return;
  }

  renderDetailTable(assetBody, assetFoot, snapshot.assets, prevSnapshot?.assets ?? null,
    (cell, name) => {
      const color = CATEGORY_COLORS[name] || '#8b949e';
      cell.innerHTML =
        `<div class="asset-name-cell">` +
        `<span class="asset-swatch" style="background:${color}"></span>${name}</div>`;
    });

  renderDetailTable(budgetBody, budgetFoot, snapshot.budget || {}, prevSnapshot?.budget ?? null,
    (cell, name) => {
      cell.textContent = name;
    });
}

/**
 * Re-render the overview section (stat cards and histogram) from appData.
 * Called on initial load and after each re-simulation.
 */
function renderOverview() {
  const { retirement, starting_total, stats, results } = appData;
  const totals = results.map(result => result.total);

  document.getElementById('age-range').textContent =
    `Age ${retirement.retirement_age} (${retirement.start_year})` +
    ` \u2192 ${retirement.end_age} (${retirement.end_year})`;

  const successRate = totals.filter(total => total >= 0).length / totals.length * 100;
  const medianChange = (stats.median - starting_total) / starting_total * 100;

  document.getElementById('starting-value').textContent = formatMoney(starting_total);
  document.getElementById('simulations-value').textContent = results.length.toLocaleString();
  document.getElementById('median-value').textContent = formatMoney(stats.median);

  const changeElement = document.getElementById('median-change');
  changeElement.textContent =
    (medianChange >= 0 ? '+' : '') + medianChange.toFixed(1) + '% vs. starting';
  changeElement.className = 'stat-sub ' + (medianChange >= 0 ? 'positive' : 'negative');

  document.getElementById('success-value').textContent = successRate.toFixed(1) + '%';

  selectedBin = -1;
  document.getElementById('bin-detail').hidden = true;

  const retirementLength = retirement.end_year - retirement.start_year;
  drawHistogram(totals, starting_total, stats.median, results, retirementLength);
}

/**
 * Switch to a different scenario, re-running with that scenario's default ages.
 * Updates the age inputs to reflect the new scenario's defaults.
 *
 * @param {string} name - Scenario name as it appears in appData.scenario.scenarios.
 */
async function switchScenario(name) {
  if (isRunning) return;

  const error = document.getElementById('run-error');
  error.textContent = '';

  if (!document.getElementById('view-detail').hidden) {
    hideDetailView();
  }

  isRunning = true;
  try {
    const response = await fetch(`/simulate?scenario=${encodeURIComponent(name)}`);
    const data = await response.json();
    if (!response.ok) {
      error.textContent = data.error || 'Simulation failed.';
      return;
    }
    appData = data;
    document.getElementById('input-retirement-age').value = appData.scenario.default_retirement_age;
    document.getElementById('input-end-age').value = appData.scenario.default_end_age;
    renderOverview();
  } catch {
    error.textContent = 'Failed to connect to server.';
  } finally {
    isRunning = false;
  }
}

/**
 * Schedule a simulation run after a short debounce delay.
 * Resets the timer on each call so rapid input changes only trigger one run.
 */
function scheduleRun() {
  clearTimeout(runDebounceTimer);
  runDebounceTimer = setTimeout(triggerRun, 600);
}

/**
 * Read the age inputs, convert to years, and re-run the simulation via /simulate.
 */
async function triggerRun() {
  if (isRunning) return;

  const retirementAge = parseInt(document.getElementById('input-retirement-age').value, 10);
  const endAge = parseInt(document.getElementById('input-end-age').value, 10);

  const error = document.getElementById('run-error');

  if (isNaN(retirementAge) || isNaN(endAge) || retirementAge >= endAge) {
    error.textContent = 'Retirement age must be before end age.';
    return;
  }

  error.textContent = '';

  const { base_year, age } = appData.scenario;
  const startYear = base_year + (retirementAge - age);
  const endYear   = base_year + (endAge - age);

  if (!document.getElementById('view-detail').hidden) {
    hideDetailView();
  }

  isRunning = true;
  try {
    const response = await fetch(`/simulate?start_year=${startYear}&end_year=${endYear}`);
    const data = await response.json();
    if (!response.ok) {
      error.textContent = data.error || 'Simulation failed.';
      return;
    }
    appData = data;
    renderOverview();
  } catch {
    error.textContent = 'Failed to connect to server.';
  } finally {
    isRunning = false;
  }
}

/**
 * Fetch simulation data from /data, set up controls, and render the initial overview.
 */
async function init() {
  try {
    appData = await fetch('/data').then(response => response.json());
  } catch (e) {
    document.getElementById('run-error').textContent = 'Failed to load simulation data. Is the server running?';
    return;
  }

  const startInput = document.getElementById('input-retirement-age');
  startInput.value = appData.scenario.default_retirement_age;
  startInput.addEventListener('input', scheduleRun);

  const endInput = document.getElementById('input-end-age');
  endInput.value = appData.scenario.default_end_age;
  endInput.addEventListener('input', scheduleRun);

  const scenarioSelect = document.getElementById('input-scenario');
  for (const name of appData.scenario.scenarios) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    option.selected = name === appData.scenario.name;
    scenarioSelect.appendChild(option);
  }
  scenarioSelect.addEventListener('change', () => switchScenario(scenarioSelect.value));

  document.getElementById('starting-card').addEventListener('click', showPreRetirementView);
  document.getElementById('median-card').addEventListener('click', () => {
    const sorted = [...appData.results].sort((a, b) => a.total - b.total);
    showDetailView(sorted[Math.floor(sorted.length / 2)]);
  });

  renderOverview();
}

window.addEventListener('load', init);
