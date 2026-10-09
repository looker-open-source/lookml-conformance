view: orders {
  sql_table_name: shared.orders ;;
  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
  }
}
