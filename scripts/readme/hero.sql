-- The 48 hours for the README's hero chart, as CSV. Run against production from the repo root:
--
--   prod exec -T db psql -U airsight -d airsight -v ON_ERROR_STOP=1 -q -f - \
--     < scripts/readme/hero.sql > docs/assets/readme/hero.csv
--
-- It picks, from the last 14 days, the full 48 hours where the correction helped most at a sensor
-- the map serves corrected values for. The chart prints both errors and the README caption says
-- how the hours were picked, so they are never presented as typical; the error badge is the
-- live average.
COPY (
    WITH nearest AS (
        SELECT DISTINCT ON (lowcost_sensor_id) lowcost_sensor_id, reference_sensor_id
        FROM sensor_pairs
        ORDER BY lowcost_sensor_id, distance_m
    ),
    hours AS (
        SELECT
            c.sensor_id,
            m.name AS station,
            c.time,
            r.pm25 AS official,
            (l.pm25_a + l.pm25_b) / 2 AS raw,
            c.pm25 AS corrected
        FROM corrected_readings c
        JOIN nearest n ON n.lowcost_sensor_id = c.sensor_id
        JOIN sensors m ON m.id = n.reference_sensor_id
        JOIN reference_readings r ON r.sensor_id = n.reference_sensor_id AND r.time = c.time
        JOIN lowcost_readings l ON l.sensor_id = c.sensor_id AND l.time = c.time
        WHERE c.time >= now() - interval '14 days'
          AND c.model_version = 'airsight-correction/1'
          AND l.pm25_a IS NOT NULL AND l.pm25_b IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM serving_sources v WHERE v.sensor_id = c.sensor_id AND v.source = 'raw'
          )
    ),
    windows AS (
        SELECT
            sensor_id,
            time AS end_time,
            count(*) OVER w AS hours,
            avg(abs(raw - official)) OVER w - avg(abs(corrected - official)) OVER w AS gain
        FROM hours
        WINDOW w AS (PARTITION BY sensor_id ORDER BY time RANGE BETWEEN interval '47 hours' PRECEDING AND CURRENT ROW)
    ),
    best AS (
        SELECT sensor_id, end_time FROM windows WHERE hours = 48 ORDER BY gain DESC LIMIT 1
    )
    SELECT
        to_char(h.time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS time,
        h.station,
        round(h.official::numeric, 2) AS official,
        round(h.raw::numeric, 2) AS raw,
        round(h.corrected::numeric, 2) AS corrected
    FROM hours h
    JOIN best b ON b.sensor_id = h.sensor_id
        AND h.time > b.end_time - interval '48 hours' AND h.time <= b.end_time
    ORDER BY h.time
) TO STDOUT WITH (FORMAT csv, HEADER);
