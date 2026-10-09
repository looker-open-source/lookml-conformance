view: orders_rollup_repeat {
  derived_table: {
    sql: SELECT customer_id, order_count
      FROM ${orders_rollup.SQL_TABLE_NAME}
      WHERE order_count > 1 ;;
  }
  dimension: customer_id { sql: ${TABLE}.customer_id ;; }
}
