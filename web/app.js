// Histogram layout constants (in SVG viewBox units)
const VIEWBOX_WIDTH = 900, VIEWBOX_HEIGHT = 300;
const MARGIN = { top: 20, right: 24, bottom: 58, left: 68 };
const INNER_WIDTH = VIEWBOX_WIDTH - MARGIN.left - MARGIN.right;
const INNER_HEIGHT = VIEWBOX_HEIGHT - MARGIN.top - MARGIN.bottom;
const HISTOGRAM_BINS = 22;

/**
 * Format a dollar amount as a compact string, e.g. $1.23M, $456K, $789.
 *
 * @param {number} amount
 * @returns {string}
 */
function formatMoney(amount) {
  const sign = amount < 0 ? '-' : '';
  const absAmount = Math.abs(amount);
  const formatted = absAmount >= 1e6 ? (absAmount / 1e6).toFixed(2) + 'M'
                  : absAmount >= 1e3 ? (absAmount / 1e3).toFixed(0) + 'K'
                  : absAmount.toFixed(0);
  return sign + '$' + formatted;
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

let selectedBin = -1;

/**
 * Render the outcome distribution histogram into the #histogram SVG element.
 *
 * @param {number[]} totals - Final portfolio value from each simulation.
 * @param {number} startingTotal - Portfolio value at retirement start (drawn as a reference marker).
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

  const xScale = value => MARGIN.left + ((value - minVal) / span) * INNER_WIDTH;
  const barWidth = INNER_WIDTH / HISTOGRAM_BINS;

  // Y-axis grid + labels
  const Y_STEPS = 4;
  for (let i = 0; i <= Y_STEPS; i++) {
    const y = MARGIN.top + (i / Y_STEPS) * INNER_HEIGHT;
    const pct = ((Y_STEPS - i) / Y_STEPS * maxCount / totals.length * 100).toFixed(0);

    svg.appendChild(svgTag('line', {
      x1: MARGIN.left, x2: MARGIN.left + INNER_WIDTH, y1: y, y2: y,
      stroke: '#30363d', 'stroke-width': '1',
    }));

    svg.appendChild(svgText(MARGIN.left - 8, y + 4, pct + '%', {
      'text-anchor': 'end', fill: '#8b949e', 'font-size': '11',
    }));
  }

  // Histogram bars
  const tooltip = document.getElementById('tooltip');
  for (let i = 0; i < HISTOGRAM_BINS; i++) {
    if (counts[i] === 0) continue;
    const barHeight = (counts[i] / maxCount) * INNER_HEIGHT;
    const barX = MARGIN.left + i * barWidth;
    const barY = MARGIN.top + INNER_HEIGHT - barHeight;

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
      x1: markerX, x2: markerX, y1: MARGIN.top, y2: MARGIN.top + INNER_HEIGHT,
      stroke: '#8b949e', 'stroke-width': '1.5', 'stroke-dasharray': '4 4',
    }));
    svg.appendChild(svgText(markerX + 5, MARGIN.top + 13, 'start', {
      fill: '#8b949e', 'font-size': '11',
    }));
  }

  // Median marker
  if (median >= minVal && median <= maxVal) {
    const markerX = xScale(median);
    svg.appendChild(svgTag('line', {
      x1: markerX, x2: markerX, y1: MARGIN.top, y2: MARGIN.top + INNER_HEIGHT,
      stroke: '#58a6ff', 'stroke-width': '2', 'stroke-dasharray': '5 3',
    }));
    svg.appendChild(svgText(markerX + 5, MARGIN.top + 28, 'median', {
      fill: '#58a6ff', 'font-size': '11',
    }));
  }

  // X-axis line
  svg.appendChild(svgTag('line', {
    x1: MARGIN.left, x2: MARGIN.left + INNER_WIDTH,
    y1: MARGIN.top + INNER_HEIGHT, y2: MARGIN.top + INNER_HEIGHT,
    stroke: '#30363d', 'stroke-width': '1',
  }));

  // X-axis labels
  const X_LABELS = 5;
  for (let i = 0; i <= X_LABELS; i++) {
    const val = minVal + (i / X_LABELS) * span;
    const x = MARGIN.left + (i / X_LABELS) * INNER_WIDTH;
    const anchor = i === 0 ? 'start' : i === X_LABELS ? 'end' : 'middle';
    svg.appendChild(svgText(x, MARGIN.top + INNER_HEIGHT + 18, formatMoney(val), {
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

    card.append(period, total, changeEl);
    grid.appendChild(card);
  }

  section.hidden = false;
  section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Fetch simulation data from /data and populate the stat cards and histogram.
 */
async function init() {
  const data = await fetch('/data').then(response => response.json());
  const { retirement, starting_total, stats, results } = data;
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
  changeElement.textContent = (medianChange >= 0 ? '+' : '') + medianChange.toFixed(1) + '% vs. starting';
  changeElement.className = 'stat-sub ' + (medianChange >= 0 ? 'positive' : 'negative');

  document.getElementById('success-value').textContent = successRate.toFixed(1) + '%';

  const retirementLength = retirement.end_year - retirement.start_year;
  drawHistogram(totals, starting_total, stats.median, results, retirementLength);
}

window.addEventListener('load', init);
