view: orders {
  sql_table_name: raw.orders ;;
  dimension: id { sql: ${TABLE}.id ;; }
  dimension: user_id { sql: ${TABLE}.user_id ;; }
  measure: count { type: count }
}
