async function fetchAll() {
  const KEY = 'sk-5104f0bb0feaf6204a0a477584e7f0e5';
  const BASE = 'https://grokai.zhubo.asia/v1/billing/usage';
  let all = [];
  let offset = 0;
  const limit = 50;

  while (true) {
    const res = await fetch(`${BASE}?limit=${limit}&offset=${offset}`, {
      headers: { 'Authorization': `Bearer ${KEY}` }
    });
    const d = await res.json();
    if (!d.items || d.items.length === 0) break;
    all = all.concat(d.items);
    if (all.length >= d.total) break;
    offset += limit;
  }

  const items = all.filter(i => i.cost > 0).sort((a, b) => a.created_at - b.created_at);
  let bal = 200;
  let totalCost = 0;

  console.log('| # | 时间 (UTC+8) | 视频时长 | 扣费 | 余额 |');
  console.log('|--:|:------------|:-------:|-----:|-----:|');

  items.forEach((i, idx) => {
    bal = Math.round((bal - i.cost) * 100) / 100;
    totalCost = Math.round((totalCost + i.cost) * 100) / 100;
    const t = new Date(i.created_at + 8 * 3600 * 1000);
    const ts = t.toISOString().replace('T', ' ').slice(5, 19);
    console.log(`| ${idx + 1} | ${ts} | ${i.video_seconds}s | $${i.cost.toFixed(2)} | $${bal.toFixed(2)} |`);
  });

  console.log('');
  console.log(`总记录: ${all.length} 条, 有效扣费: ${items.length} 笔`);
  console.log(`累计消费: $${totalCost.toFixed(2)}`);
  console.log(`当前余额: $${bal.toFixed(2)}`);
}
fetchAll();
