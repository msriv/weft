-- GDELT is a discovery feed, not a source of record (D11). This only lists candidate URLs;
-- nothing here is treated as a report until the fetcher has fetched and extracted it.
SELECT
  DocumentIdentifier AS url,
  SourceCommonName AS domain,
  PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING)) AS published_at,
  V2Themes AS themes,
  V2Locations AS locations,
  CURRENT_TIMESTAMP() AS discovered_at
FROM `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
  AND REGEXP_CONTAINS(V2Themes, r"""${theme_regex}""")
  AND DocumentIdentifier NOT IN (
    SELECT url FROM `${project_id}.${dataset_id}.gdelt_candidates`
  )
