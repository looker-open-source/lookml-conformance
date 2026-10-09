view: orders {
  sql_table_name: raw.orders ;;
  dimension: info {
    type: string
    sql: ${TABLE}.info ;;
  }
  measure: errors {
    type: count
  }
}
