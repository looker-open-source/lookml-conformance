view: orders {
  sql_table_name: raw.orders ;;
  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
    label: "Id"
  }
}
