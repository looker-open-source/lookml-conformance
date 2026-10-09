view: orders_rollup {
  derived_table: {
    sql: SELECT customer_id, COUNT(*) AS order_count
      FROM ${orders.SQL_TABLE_NAME}
      GROUP BY 1 ;;
  }
  dimension: customer_id { sql: ${TABLE}.customer_id ;; }
}
