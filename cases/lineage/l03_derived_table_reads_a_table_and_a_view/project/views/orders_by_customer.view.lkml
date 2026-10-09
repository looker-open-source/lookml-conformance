view: orders_by_customer {
  derived_table: {
    sql: SELECT c.id AS customer_id, COUNT(o.id) AS order_count
      FROM raw.customers AS c
      LEFT JOIN ${orders.SQL_TABLE_NAME} AS o ON o.customer_id = c.id
      GROUP BY 1 ;;
  }
  dimension: customer_id { sql: ${TABLE}.customer_id ;; }
}
