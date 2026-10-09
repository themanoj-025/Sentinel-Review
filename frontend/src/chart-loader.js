// Lazy-loaded Chart.js for /stats/ page only
// This module is dynamically imported from the stats page template.
// It keeps the ~700KB Chart.js bundle off non-stats pages.

export async function initCharts(config) {
  const { default: Chart } = await import(
    /* webpackChunkName: "chart" */
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js'
  );
  return renderCharts(Chart, config);
}

function renderCharts(Chart, config) {
  const COLORS = {
    sentinel: '#6366f1',
    sentinelLight: '#818cf8',
    bug: '#ef4444',
    security: '#a855f7',
    style: '#10b981',
    suggestion: '#3b82f6',
    success: '#22c55e',
    warning: '#f59e0b',
    danger: '#ef4444',
    grid: '#1f2937',
    text: '#9ca3af',
    background: '#111827',
  };

  // Usefulness bar chart
  const usefulnessCtx = document.getElementById('usefulnessChart');
  if (usefulnessCtx && config.usefulness?.length) {
    const cats = config.usefulness;
    new Chart(usefulnessCtx, {
      type: 'bar',
      data: {
        labels: cats.map(c => c.label),
        datasets: [{
          label: 'Usefulness Rate (%)',
          data: cats.map(c => c.usefulness_rate),
          backgroundColor: cats.map(c => COLORS[c.category] || COLORS.sentinel),
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1f2937',
            titleColor: '#f9fafb',
            bodyColor: '#d1d5db',
            borderColor: '#374151',
            borderWidth: 1,
            callbacks: {
              afterBody: (items) => {
                const cat = cats[items[0].dataIndex];
                return `👍 ${cat.upvotes} upvotes / 👎 ${cat.downvotes} downvotes`;
              },
            },
          },
        },
        scales: {
          y: { beginAtZero: true, max: 100, grid: { color: COLORS.grid }, ticks: { color: COLORS.text, callback: v => v + '%' } },
          x: { grid: { display: false }, ticks: { color: COLORS.text } },
        },
      },
    });
  }

  // Volume donut chart
  const volumeCtx = document.getElementById('volumeChart');
  if (volumeCtx && config.volume?.length) {
    const cats = config.volume;
    new Chart(volumeCtx, {
      type: 'doughnut',
      data: {
        labels: cats.map(c => c.category.charAt(0).toUpperCase() + c.category.slice(1)),
        datasets: [{
          data: cats.map(c => c.count),
          backgroundColor: cats.map(c => COLORS[c.category] || COLORS.sentinel),
          borderWidth: 2,
          borderColor: COLORS.background,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { color: COLORS.text, padding: 12, usePointStyle: true, pointStyle: 'circle' } },
          tooltip: {
            backgroundColor: '#1f2937',
            titleColor: '#f9fafb',
            bodyColor: '#d1d5db',
            borderColor: '#374151',
            borderWidth: 1,
            callbacks: {
              label: (item) => {
                const total = item.dataset.data.reduce((a, b) => a + b, 0);
                const pct = ((item.parsed / total) * 100).toFixed(1);
                return ` ${item.label}: ${item.parsed} comments (${pct}%)`;
              },
            },
          },
        },
        cutout: '65%',
      },
    });
  }

  // Trend line chart
  const trendCtx = document.getElementById('trendsChart');
  if (trendCtx && config.trends?.length) {
    new Chart(trendCtx, {
      type: 'line',
      data: {
        labels: config.trends.map(r => r.date),
        datasets: [{
          label: 'Reviews',
          data: config.trends.map(r => r.count),
          borderColor: COLORS.sentinel,
          backgroundColor: COLORS.sentinel + '20',
          fill: true,
          tension: 0.4,
          pointRadius: 4,
          pointBackgroundColor: COLORS.sentinel,
          pointBorderColor: COLORS.sentinelLight,
          pointBorderWidth: 2,
          pointHoverRadius: 6,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1f2937', titleColor: '#f9fafb', bodyColor: '#d1d5db', borderColor: '#374151', borderWidth: 1 } },
        scales: {
          y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { color: COLORS.text, stepSize: 1 } },
          x: { grid: { display: false }, ticks: { color: COLORS.text } },
        },
        interaction: { intersect: false, mode: 'index' },
      },
    });
  }

  // Severity distribution
  const severityCtx = document.getElementById('severityChart');
  if (severityCtx && config.usefulness?.length) {
    const cats = config.usefulness;
    new Chart(severityCtx, {
      type: 'bar',
      data: {
        labels: cats.map(c => c.label),
        datasets: [
          { label: 'Upvotes (👍)', data: cats.map(c => c.upvotes), backgroundColor: COLORS.success + '80', borderRadius: 2 },
          { label: 'Downvotes (👎)', data: cats.map(c => c.downvotes), backgroundColor: COLORS.danger + '80', borderRadius: 2 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: COLORS.text, usePointStyle: true, pointStyle: 'circle' } }, tooltip: { backgroundColor: '#1f2937', titleColor: '#f9fafb', bodyColor: '#d1d5db', borderColor: '#374151', borderWidth: 1 } },
        scales: {
          y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { color: COLORS.text, stepSize: 1 } },
          x: { grid: { display: false }, ticks: { color: COLORS.text } },
        },
      },
    });
  }
}
