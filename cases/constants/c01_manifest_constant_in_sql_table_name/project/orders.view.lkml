view: orders {
  sql_table_name: @{ANALYTICS_SCHEMA}.orders ;;
  dimension: id { sql: ${TABLE}.id ;; }
}
