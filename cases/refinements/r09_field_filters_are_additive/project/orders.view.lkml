view: orders {
  sql_table_name: raw.orders ;;
  dimension: status { sql: ${TABLE}.status ;; }
  dimension: region { sql: ${TABLE}.region ;; }
  measure: n {
    type: count
    filters: [status: "complete"]
  }
}
