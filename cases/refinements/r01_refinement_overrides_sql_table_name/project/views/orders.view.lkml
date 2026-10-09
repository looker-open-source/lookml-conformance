view: orders {
  sql_table_name: raw.orders ;;
  dimension: id { sql: ${TABLE}.id ;; }
}
