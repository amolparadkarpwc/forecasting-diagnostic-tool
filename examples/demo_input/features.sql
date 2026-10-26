SELECT s.series_id, s.week_start, p.price
FROM sales s
JOIN price_actuals p ON p.week_start >= s.week_start
